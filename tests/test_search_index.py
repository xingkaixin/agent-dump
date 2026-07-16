"""Tests for search_index.py module."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading
from unittest import mock

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.search_index import (
    SearchIndex,
    _build_fts_query,
    _extract_related_source_paths,
    _extract_session_searchable_text,
    _has_cjk,
    _has_fts5,
    _select_fts_table,
    _serialize_for_search,
    _session_updated_signal,
)


class DummyAgent(BaseAgent):
    """Minimal agent for testing."""

    def __init__(self, name: str = "codex", session_data: dict[str, dict] | None = None):
        super().__init__(name=name, display_name=f"Dummy-{name}")
        self._session_data = session_data or {}

    def scan(self) -> list[Session]:
        return []

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int = 7) -> list[Session]:
        return []

    def export_session(self, session: Session, output_dir: Path) -> Path:
        raise NotImplementedError

    def get_session_data(self, session: Session) -> dict:
        return self._session_data.get(session.id, {})


def make_session(session_id: str, title: str, source_path: Path) -> Session:
    return Session(
        id=session_id,
        title=title,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        updated_at=datetime(2026, 1, 1, 12, 0, 0),
        source_path=source_path,
        metadata={},
    )


class TestHasFts5:
    def test_detects_fts5_availability(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = __import__("sqlite3").connect(db_path)
        result = _has_fts5(conn)
        conn.close()
        assert isinstance(result, bool)


class TestHasCjk:
    def test_detects_chinese(self):
        assert _has_cjk("中文") is True

    def test_no_cjk_in_ascii(self):
        assert _has_cjk("hello world") is False

    def test_mixed(self):
        assert _has_cjk("hello中文") is True


class TestSelectFtsTable:
    def test_cjk_uses_unicode(self):
        assert _select_fts_table("修复问题") == "sessions_fts"
        assert _select_fts_table("报错") == "sessions_fts"

    def test_ascii_uses_trigram(self):
        assert _select_fts_table("hello") == "sessions_fts_trigram"


class TestBuildFtsQuery:
    def test_empty_returns_empty(self):
        assert _build_fts_query("") == ""

    def test_passthrough_operators(self):
        assert _build_fts_query("hello AND world") == "hello AND world"
        assert _build_fts_query('"exact phrase"') == '"exact phrase"'

    def test_simple_keyword(self):
        assert _build_fts_query("hello") == "hello"

    def test_multi_word(self):
        assert _build_fts_query("hello world") == "hello world"


class TestSerializeForSearch:
    def test_string_passthrough(self):
        assert _serialize_for_search("hello") == "hello"

    def test_dict_to_json(self):
        assert _serialize_for_search({"key": "value"}) == '{"key": "value"}'


class TestSessionUpdatedSignal:
    def test_signal_uses_updated_at(self, tmp_path):
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")

        assert _session_updated_signal(session) == session.updated_at.replace(tzinfo=timezone.utc).timestamp()

    def test_related_paths_raise_signal(self, tmp_path):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        context_file = session_dir / "context.jsonl"
        context_file.write_text("context")
        session = make_session("s1", "Test", session_dir)
        session.metadata = {"context_file": str(context_file)}

        assert _session_updated_signal(session) >= context_file.stat().st_mtime

    def test_missing_related_paths_fall_back_to_updated_at(self, tmp_path):
        session = make_session("s1", "Test", tmp_path / "session")
        session.metadata = {"context_file": str(tmp_path / "missing.jsonl")}

        assert _session_updated_signal(session) == session.updated_at.replace(tzinfo=timezone.utc).timestamp()

    def test_extract_related_source_paths_from_session_metadata(self, tmp_path):
        session_dir = tmp_path / "session"
        context_file = session_dir / "context.jsonl"
        wire_file = session_dir / "wire.jsonl"
        session = make_session(
            "s1",
            "Test",
            session_dir,
        )
        session.metadata = {
            "context_file": str(context_file),
            "wire_file": str(wire_file),
        }

        assert _extract_related_source_paths(session) == (context_file, wire_file)


class TestExtractSessionSearchableText:
    def test_extracts_text_parts(self):
        agent = DummyAgent(
            session_data={
                "s1": {
                    "messages": [
                        {"role": "user", "parts": [{"type": "text", "text": "Hello world"}]},
                        {"role": "assistant", "parts": [{"type": "text", "text": "Hi there"}]},
                    ]
                }
            }
        )
        session = make_session("s1", "Test", Path("/tmp/s1.jsonl"))
        text = _extract_session_searchable_text(agent, session)
        assert "Hello world" in text
        assert "Hi there" in text

    def test_extracts_reasoning(self):
        agent = DummyAgent(
            session_data={
                "s1": {
                    "messages": [
                        {"role": "assistant", "parts": [{"type": "reasoning", "text": "Let me think"}]},
                    ]
                }
            }
        )
        session = make_session("s1", "Test", Path("/tmp/s1.jsonl"))
        text = _extract_session_searchable_text(agent, session)
        assert "Let me think" in text

    def test_extracts_tool_state(self):
        agent = DummyAgent(
            session_data={
                "s1": {
                    "messages": [
                        {
                            "role": "assistant",
                            "parts": [
                                {
                                    "type": "tool",
                                    "tool": "bash",
                                    "state": {
                                        "arguments": {"command": "ls -la"},
                                        "output": [{"type": "text", "text": "file1.txt"}],
                                        "prompt": "run bash",
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        )
        session = make_session("s1", "Test", Path("/tmp/s1.jsonl"))
        text = _extract_session_searchable_text(agent, session)
        assert "ls -la" in text
        assert "file1.txt" in text
        assert "run bash" in text

    def test_fallback_to_source(self, tmp_path):
        source = tmp_path / "session.jsonl"
        source.write_text('{"message": {"role": "user", "content": "fallback text"}}')
        agent = DummyAgent(session_data={})
        session = make_session("s1", "Test", source)
        text = _extract_session_searchable_text(agent, session)
        assert "fallback text" in text


class TestSearchIndex:
    def test_incremental_adds_new_sessions(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword hit"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        added, removed = index.update(agent, [session])
        assert added == 1
        assert removed == 0

        results = index.search("keyword")
        assert len(results) == 1
        assert results[0].session_id == "s1"
        assert results[0].title == "Test"

    def test_update_extracts_sessions_concurrently_before_serial_writes(self, tmp_path) -> None:
        class ThreadTracingSearchIndex(SearchIndex):
            def __init__(self, db_path: Path) -> None:
                super().__init__(db_path)
                self.sql_threads: set[int] = set()

            def _get_connection(self) -> sqlite3.Connection:
                conn = super()._get_connection()
                conn.set_trace_callback(self._record_sql_thread)
                return conn

            def _record_sql_thread(self, _sql: str) -> None:
                self.sql_threads.add(threading.get_ident())

        index = ThreadTracingSearchIndex(tmp_path / "index.db")
        agent = DummyAgent()
        sessions = [
            make_session("s1", "Test 1", tmp_path / "s1.jsonl"),
            make_session("s2", "Test 2", tmp_path / "s2.jsonl"),
        ]
        for session in sessions:
            session.source_path.write_text("data")

        release_reads = threading.Event()
        read_lock = threading.Lock()
        started_sessions: set[str] = set()
        worker_threads: set[int] = set()
        calling_thread = threading.get_ident()

        def extract_text(_agent: BaseAgent, session: Session) -> str:
            with read_lock:
                started_sessions.add(session.id)
                worker_threads.add(threading.get_ident())
                if len(started_sessions) == 2:
                    release_reads.set()
            if not release_reads.wait(timeout=5):
                raise AssertionError("search index reads did not overlap")
            return f"keyword {session.id}"

        with mock.patch("agent_dump.search_index._extract_session_searchable_text", side_effect=extract_text):
            added, removed = index.update(agent, sessions)

        assert (added, removed) == (2, 0)
        assert len(worker_threads) == 2
        assert calling_thread not in worker_threads
        assert index.sql_threads == {calling_thread}
        assert {result.session_id for result in index.search("keyword")} == {"s1", "s2"}

    def test_incremental_skips_unchanged(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        added, removed = index.update(agent, [session])
        assert added == 0
        assert removed == 0

    def test_incremental_detects_updated_at_change(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "old"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        agent._session_data["s1"]["messages"][0]["parts"][0]["text"] = "new keyword"
        session.updated_at = session.updated_at + timedelta(minutes=5)

        added, removed = index.update(agent, [session])
        assert added == 1
        assert len(index.search("new")) == 1

    def test_update_hints_progress_for_bulk_indexing(self, tmp_path, capsys):
        """测试待索引会话达到阈值时向 stderr 提示进度"""
        index = SearchIndex(tmp_path / "index.db")
        session_data = {
            f"s{i}": {"messages": [{"role": "user", "parts": [{"type": "text", "text": f"content {i}"}]}]}
            for i in range(10)
        }
        agent = DummyAgent(session_data=session_data)
        sessions = []
        for i in range(10):
            session = make_session(f"s{i}", f"Test {i}", tmp_path / f"s{i}.jsonl")
            session.source_path.write_text("data")
            sessions.append(session)

        index.update(agent, sessions)

        captured = capsys.readouterr()
        assert "正在更新 Dummy-codex 的搜索索引（10 个会话" in captured.err
        assert captured.out == ""

    def test_update_stays_silent_for_small_increments(self, tmp_path, capsys):
        """测试少量增量更新不输出进度提示"""
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "one"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        assert capsys.readouterr().err == ""

    def test_sessions_sharing_source_path_are_indexed_independently(self, tmp_path):
        """SQLite provider 的所有会话共享同一 db 文件，索引身份必须按 session id 区分"""
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "alpha"}]}]},
                "s2": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "bravo"}]}]},
            }
        )
        shared_source = tmp_path / "shared.db"
        shared_source.write_text("data")
        session1 = make_session("s1", "Test 1", shared_source)
        session2 = make_session("s2", "Test 2", shared_source)

        added, removed = index.update(agent, [session1, session2])
        assert (added, removed) == (2, 0)
        assert len(index.search("alpha")) == 1
        assert len(index.search("bravo")) == 1

        # 只更新 s2：s1 不应被重建
        session2.updated_at = session2.updated_at + timedelta(minutes=5)
        added, removed = index.update(agent, [session1, session2])
        assert (added, removed) == (1, 0)

        # 只保留 s1：仅 s2 的索引行被清除
        added, removed = index.update(agent, [session1])
        assert (added, removed) == (0, 1)
        assert len(index.search("alpha")) == 1
        assert len(index.search("bravo")) == 0

    def test_old_schema_is_migrated_on_initialize(self, tmp_path):
        """旧版按 source_path 主键的索引库会被重建为按 (agent, session_id)"""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE index_state (
                source_path TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                session_id TEXT NOT NULL,
                mtime REAL NOT NULL,
                indexed_at REAL NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        index = SearchIndex(db_path)
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        added, removed = index.update(agent, [session])
        assert (added, removed) == (1, 0)
        assert len(index.search("keyword")) == 1

    def test_delete_stale_sessions(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        assert len(index.search("keyword")) == 1

        # Update with empty sessions list
        added, removed = index.update(agent, [])
        assert removed == 1
        assert len(index.search("keyword")) == 0

    def test_search_multi_keyword(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "error timeout bug"}]}]}
            }
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        results = index.search("error timeout")
        assert len(results) == 1

    def test_search_cjk(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "修复认证模块的问题"}]}]}
            }
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        # Short CJK (2 chars) uses unicode61
        results = index.search("认证")
        assert len(results) == 1
        assert results[0].snippet == "修复**认证**模块的问题"

        # Longer CJK (3+ chars) uses trigram
        results = index.search("修复问题")
        assert len(results) == 1

    def test_search_snippet(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {
                    "messages": [
                        {
                            "role": "user",
                            "parts": [{"type": "text", "text": "the quick brown fox jumps over the lazy dog"}],
                        }
                    ]
                }
            }
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        results = index.search("fox")
        assert len(results) == 1
        assert results[0].snippet is not None
        assert "fox" in results[0].snippet or "**fox**" in results[0].snippet

    def test_search_with_agent_filter(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent1 = DummyAgent(
            name="codex",
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "codex keyword"}]}]}},
        )
        agent2 = DummyAgent(
            name="kimi",
            session_data={"s2": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "kimi keyword"}]}]}},
        )
        session1 = make_session("s1", "Test1", tmp_path / "s1.jsonl")
        session2 = make_session("s2", "Test2", tmp_path / "s2.jsonl")
        session1.source_path.write_text("data")
        session2.source_path.write_text("data")

        index.update(agent1, [session1])
        index.update(agent2, [session2])

        results = index.search("keyword", agent_names={"codex"})
        assert len(results) == 1
        assert results[0].agent_name == "codex"

    def test_clear_agent(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        assert len(index.search("keyword")) == 1

        deleted = index.clear_agent("codex")
        assert deleted == 1
        assert len(index.search("keyword")) == 0

    def test_clear_agent_deletes_fts_rows_per_table(self, tmp_path):
        class TracedSearchIndex(SearchIndex):
            def __init__(self, db_path: Path | None = None) -> None:
                super().__init__(db_path)
                self.delete_statements: list[str] = []

            def _get_connection(self):
                conn = super()._get_connection()
                conn.set_trace_callback(
                    lambda sql: (
                        self.delete_statements.append(sql) if sql.startswith("DELETE FROM sessions_fts") else None
                    )
                )
                return conn

        index = TracedSearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "one keyword"}]}]},
                "s2": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "two keyword"}]}]},
            }
        )
        session1 = make_session("s1", "Test 1", tmp_path / "s1.jsonl")
        session2 = make_session("s2", "Test 2", tmp_path / "s2.jsonl")
        session1.source_path.write_text("data")
        session2.source_path.write_text("data")

        index.update(agent, [session1, session2])
        index.delete_statements.clear()

        deleted = index.clear_agent("codex")

        assert deleted == 2
        assert len(index.delete_statements) == 2
        assert all("rowid =" not in statement for statement in index.delete_statements)

    def test_rebuild(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        count = index.rebuild(agent, [session])
        assert count == 1
        assert len(index.search("keyword")) == 1

    def test_get_stats(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        stats = index.get_stats()
        assert "codex" in stats
        assert stats["codex"]["sessions"] == 1


class TestSearchIndexFallback:
    def test_unavailable_returns_empty(self, tmp_path):
        with mock.patch("agent_dump.search_index._has_fts5", return_value=False):
            index = SearchIndex(tmp_path / "index.db")
            assert index.is_available is False
            assert index.search("anything") == []
            assert index.get_stats() == {}


class TestQueryFilterIntegration:
    def test_filter_sessions_uses_index_when_available(self, tmp_path):
        from agent_dump.query_filter import filter_sessions

        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "indexed keyword"}]}]}
            }
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")
        index.update(agent, [session])

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            results = filter_sessions(agent, [session], "indexed keyword")
            assert len(results) == 1

    def test_filter_sessions_fallback_when_index_fails(self, tmp_path):
        from agent_dump.query_filter import filter_sessions

        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fallback keyword"}]}]}
            }
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("fallback keyword")

        with mock.patch("agent_dump.query_filter.SearchIndex", side_effect=Exception("boom")):
            results = filter_sessions(agent, [session], "fallback keyword")
            assert len(results) == 1
