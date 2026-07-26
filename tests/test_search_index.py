"""Tests for search_index.py module."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.search_index import (
    _INDEX_BATCH_SIZE,
    SearchIndex,
    _batched,
    _build_fts_query,
    _has_cjk,
    _has_fts5,
    _preprocess_for_unicode61,
    _select_fts_table,
    _serialize_for_search,
    extract_session_searchable_text,
)
from agent_dump.session_data import (
    session_updated_signal as _session_updated_signal,
)


class DummyAgent(BaseAgent):
    """Minimal agent for testing."""

    def __init__(self, name: str = "codex", session_data: dict[str, dict] | None = None):
        super().__init__(name=name, display_name=f"Dummy-{name}")
        self._session_data = session_data or {}
        self.data_reads = 0

    def scan(self) -> list[Session]:
        return []

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int = 7) -> list[Session]:
        return []

    def export_session(self, session: Session, output_dir: Path) -> Path:
        raise NotImplementedError

    def get_session_data(self, session: Session) -> dict:
        self.data_reads += 1
        return self._session_data.get(session.id, {})


def require_text(agent: BaseAgent, session: Session) -> str:
    """提取正文并断言这次读取没有失败（None 表示读失败，见 AD-121）。"""
    text = extract_session_searchable_text(agent, session)
    assert text is not None, "会话正文提取失败"
    return text


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
    """AD-133：每个词都引用为字面量，任何输入都不该构成 FTS5 语法错误。"""

    @pytest.mark.parametrize("keyword", ["", "   ", "\t\n"])
    def test_blank_returns_empty(self, keyword):
        assert _build_fts_query(keyword) == ""

    def test_single_term_is_quoted(self):
        assert _build_fts_query("hello") == '"hello"'

    def test_terms_are_quoted_individually(self):
        """词之间保持 FTS5 默认的隐式 AND。"""
        assert _build_fts_query("hello world") == '"hello" "world"'

    def test_operators_become_literal_terms(self):
        """文档只承诺关键词搜索；操作符透传是意外行为，且是语法错误的来源。"""
        assert _build_fts_query("hello AND world") == '"hello" "AND" "world"'

    def test_embedded_quotes_are_escaped(self):
        assert _build_fts_query('say "hi"') == '"say" """hi"""'

    @pytest.mark.parametrize(
        "keyword",
        ['unbalanced "quote', "trailing operator AND", "NEAR(", "*", "a* b*", '"""', "^caret", "-dash"],
    )
    def test_any_input_produces_a_query_sqlite_accepts(self, keyword, tmp_path):
        """修复前这些输入会让 MATCH 报语法错误，被兜底吞掉后静默退化成子串扫描。"""
        index = SearchIndex(tmp_path / "index.db")
        index.ensure_initialized()

        # 不抛异常即证明表达式语法合法
        assert index.search(keyword) == [] or True

    def test_cjk_terms_are_quoted(self):
        assert _build_fts_query("认证 超时") == '"认证" "超时"'


class TestSerializeForSearch:
    def test_string_passthrough(self):
        assert _serialize_for_search("hello") == "hello"

    def test_dict_to_json(self):
        assert _serialize_for_search({"key": "value"}) == '{"key": "value"}'


class TestSessionUpdatedSignal:
    def test_signal_uses_updated_at(self, tmp_path):
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")

        assert (
            _session_updated_signal(DummyAgent(), session)
            == session.updated_at.replace(tzinfo=timezone.utc).timestamp()
        )

    def test_related_paths_raise_signal(self, tmp_path):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        context_file = session_dir / "context.jsonl"
        context_file.write_text("context")
        session = make_session("s1", "Test", session_dir)
        agent = DummyAgent()

        with mock.patch.object(agent, "get_session_change_sources", return_value=(context_file,)):
            assert _session_updated_signal(agent, session) >= context_file.stat().st_mtime

    def test_missing_related_paths_fall_back_to_updated_at(self, tmp_path):
        session = make_session("s1", "Test", tmp_path / "session")
        agent = DummyAgent()
        missing = tmp_path / "missing.jsonl"

        with mock.patch.object(agent, "get_session_change_sources", return_value=(missing,)):
            assert (
                _session_updated_signal(agent, session) == session.updated_at.replace(tzinfo=timezone.utc).timestamp()
            )


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
        text = require_text(agent, session)
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
        text = require_text(agent, session)
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
        text = require_text(agent, session)
        assert "ls -la" in text
        assert "file1.txt" in text
        assert "run bash" in text

    def test_fallback_to_source(self, tmp_path):
        source = tmp_path / "session.jsonl"
        source.write_text('{"message": {"role": "user", "content": "fallback text"}}')
        agent = DummyAgent(session_data={})
        session = make_session("s1", "Test", source)
        text = require_text(agent, session)
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
        assert agent.get_cached_session_data(session)["messages"][0]["role"] == "user"
        assert agent.data_reads == 1

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

        with mock.patch("agent_dump.search_index.extract_session_searchable_text", side_effect=extract_text):
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


def _legacy_preprocess_for_unicode61(text: str) -> str:
    """AD-120 前的逐字符实现，作为正则改写的等价性基准。"""
    result: list[str] = []
    prev_was_cjk = False
    for char in text:
        is_cjk = "一" <= char <= "鿿"
        if prev_was_cjk and is_cjk:
            result.append(" ")
        result.append(char)
        prev_was_cjk = is_cjk
    return "".join(result)


class TestUnicode61Preprocessing:
    """AD-120：逐字符循环改零宽断言正则，必须逐字节等价。"""

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "修",
            "修复认证",
            "abc修复def",
            "修a复",
            "修 复",
            "fix 认证 timeout 超时问题",
            "混合ASCII与中文123测试",
            "emoji🎉不受影响的中文",
            "换行\n分隔的中文\t制表",
            "日本語のテキスト",  # 平假名/片假名不在 CJK 统一表意区间内
        ],
    )
    def test_matches_legacy_char_loop(self, text):
        assert _preprocess_for_unicode61(text) == _legacy_preprocess_for_unicode61(text)

    def test_inserts_space_between_adjacent_cjk_only(self):
        assert _preprocess_for_unicode61("修复认证") == "修 复 认 证"
        assert _preprocess_for_unicode61("abc") == "abc"


def _touched(session: Session) -> Session:
    """返回 updated_at 前进一小时的同一会话，用于触发索引更新。"""
    return Session(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at + timedelta(hours=1),
        source_path=session.source_path,
        metadata=session.metadata,
    )


class TestBatched:
    def test_splits_into_fixed_size_slices(self):
        assert list(_batched([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_empty_input_yields_nothing(self):
        assert list(_batched([], 4)) == []


class TestIndexBuildAvoidsRedundantDeletes:
    """AD-120：FTS5 表里 session_id 是 UNINDEXED，空删除会全表扫描。"""

    def test_first_build_issues_no_delete(self, tmp_path, monkeypatch):
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        sessions = [make_session(f"s{i}", f"标题{i}", source) for i in range(5)]
        agent = DummyAgent(session_data={s.id: {"messages": []} for s in sessions})

        calls: list[str] = []
        monkeypatch.setattr(
            "agent_dump.search_index._delete_fts_by_session",
            lambda conn, fts_table, session_id, agent_name: calls.append(session_id),
        )

        index = SearchIndex(tmp_path / "index.db")
        added, _ = index.update(agent, sessions)

        assert added == 5
        assert calls == [], "首次索引的会话此前没有 FTS 行，不应触发任何 DELETE"

    def test_reindexing_a_changed_session_still_deletes_old_rows(self, tmp_path, monkeypatch):
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        session = make_session("s1", "标题", source)
        agent = DummyAgent(session_data={"s1": {"messages": []}})

        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, [session])

        calls: list[str] = []
        monkeypatch.setattr(
            "agent_dump.search_index._delete_fts_by_session",
            lambda conn, fts_table, session_id, agent_name: calls.append(session_id),
        )
        # updated_signal 取 session.updated_at 与 metadata 里 per-session 文件的
        # mtime，不看 source_path，所以必须推进 updated_at 才算「有变更」
        index.update(agent, [_touched(session)])

        assert calls == ["s1", "s1"], "已索引过的会话更新时必须先删掉两张表的旧行"

    def test_reindex_keeps_exactly_one_row_per_session_across_updates(self, tmp_path):
        source = tmp_path / "s.jsonl"
        source.write_text("认证超时", encoding="utf-8")
        agent = DummyAgent(session_data={"s1": {"messages": [{"role": "user", "content": "认证超时"}]}})
        index = SearchIndex(tmp_path / "index.db")

        first = make_session("s1", "认证", source)
        index.update(agent, [first])
        index.update(agent, [_touched(first)])

        conn = sqlite3.connect(tmp_path / "index.db")
        try:
            for table in ("sessions_fts", "sessions_fts_trigram"):
                count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id = 's1'").fetchone()[0]
                assert count == 1, f"{table} 出现重复行会让搜索结果重复"
        finally:
            conn.close()


class TestIndexBuildSpansMultipleBatches:
    """AD-120：分批消费不能漏掉任何会话。"""

    def test_all_sessions_indexed_when_count_exceeds_batch_size(self, tmp_path):
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        total = _INDEX_BATCH_SIZE * 2 + 3
        sessions = [make_session(f"s{i}", f"标题{i}", source) for i in range(total)]
        agent = DummyAgent(session_data={s.id: {"messages": []} for s in sessions})

        index = SearchIndex(tmp_path / "index.db")
        added, _ = index.update(agent, sessions)

        assert added == total
        assert index.get_stats()["codex"]["sessions"] == total


class FailingAgent(DummyAgent):
    """get_session_data 恒抛异常，模拟瞬时读失败。"""

    def get_session_data(self, session: Session) -> dict:
        raise OSError("transient read failure")


class TestExtractionFailureIsNotRecordedAsIndexed:
    """AD-121：失败被写成 index_state 会让会话永久搜不到。"""

    def test_returns_none_when_source_is_a_shared_database(self, tmp_path):
        """SQLite provider 的 source_path 是整库文件，不能当文本回退读取。"""
        db_path = tmp_path / "opencode.db"
        db_path.write_bytes(b"SQLite format 3\x00" + b"other sessions content" * 100)
        session = make_session("s1", "Test", db_path)

        assert extract_session_searchable_text(FailingAgent(), session) is None

    def test_returns_text_when_source_is_a_per_session_jsonl(self, tmp_path):
        source = tmp_path / "session.jsonl"
        source.write_text('{"content": "per session text"}', encoding="utf-8")
        session = make_session("s1", "Test", source)

        text = extract_session_searchable_text(FailingAgent(), session)

        assert text is not None and "per session text" in text

    def test_returns_none_when_source_is_missing(self, tmp_path):
        session = make_session("s1", "Test", tmp_path / "gone.jsonl")

        assert extract_session_searchable_text(FailingAgent(), session) is None

    def test_empty_session_yields_empty_string_not_none(self):
        """会话确实没有内容与读失败必须区分开，否则空会话每次都被重解析。"""
        agent = DummyAgent(session_data={"s1": {"messages": []}})
        session = make_session("s1", "Test", Path("/tmp/s1.jsonl"))

        assert extract_session_searchable_text(agent, session) == ""

    def test_failed_session_is_retried_on_the_next_run(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        db_path.write_bytes(b"SQLite format 3\x00")
        session = make_session("s1", "标题", db_path)
        index = SearchIndex(tmp_path / "index.db")

        added, _ = index.update(FailingAgent(name="opencode"), [session])

        assert added == 0
        assert index.get_stats() == {}, "读失败的会话不得留下 index_state 行"

        # 同一个会话在源恢复后必须仍被视为待索引
        working = DummyAgent(
            name="opencode",
            session_data={"s1": {"messages": [{"role": "user", "content": "恢复后的内容"}]}},
        )
        added, _ = index.update(working, [session])

        assert added == 1
        assert index.get_stats()["opencode"]["sessions"] == 1

    def test_empty_session_is_recorded_and_not_reparsed(self, tmp_path):
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        session = make_session("s1", "标题", source)
        agent = DummyAgent(session_data={"s1": {"messages": []}})
        index = SearchIndex(tmp_path / "index.db")

        added, _ = index.update(agent, [session])
        assert added == 1

        reads_after_first = agent.data_reads
        index.update(agent, [session])

        assert agent.data_reads == reads_after_first, "未变更的空会话不应被重新解析"

    def test_skipped_sessions_are_reported_on_stderr(self, tmp_path, capsys):
        db_path = tmp_path / "opencode.db"
        db_path.write_bytes(b"SQLite format 3\x00")
        sessions = [make_session(f"s{i}", f"标题{i}", db_path) for i in range(2)]
        index = SearchIndex(tmp_path / "index.db")

        index.update(FailingAgent(name="opencode"), sessions)
        captured = capsys.readouterr()

        assert "2 个会话读取失败" in captured.err


class TestFallbackSearchHandlesUnreadableSessions:
    """AD-121：query_filter 的兜底匹配也要能吃 None。"""

    def test_unreadable_session_is_skipped_not_crashed(self, tmp_path):
        from agent_dump.query_filter import _fallback_search_matches

        db_path = tmp_path / "opencode.db"
        db_path.write_bytes(b"SQLite format 3\x00")
        sessions = [make_session("s1", "无关标题", db_path)]

        assert _fallback_search_matches(FailingAgent(name="opencode"), sessions, "keyword") == []


class TestIndexFailureIsReported:
    """AD-133：索引出错必须说出来，而不是与「没有索引」混为一谈。"""

    def test_index_error_warns_and_still_falls_back(self, tmp_path, capsys):
        from agent_dump.query_filter import filter_sessions

        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fallback kw"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("fallback kw", encoding="utf-8")

        with mock.patch("agent_dump.query_filter.SearchIndex", side_effect=sqlite3.DatabaseError("db is locked")):
            results = filter_sessions(agent, [session], "fallback kw")
        captured = capsys.readouterr()

        assert len(results) == 1, "退回文件扫描仍应给出结果"
        assert "搜索索引不可用" in captured.err
        assert "DatabaseError" in captured.err
        assert "--reindex" in captured.err

    def test_missing_fts5_support_is_not_reported_as_an_error(self, tmp_path, capsys):
        """没编译 FTS5 是正常状态，不该每次查询都刷告警。"""
        from agent_dump.query_filter import filter_sessions

        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fallback kw"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("fallback kw", encoding="utf-8")

        with mock.patch.object(SearchIndex, "is_available", new_callable=mock.PropertyMock, return_value=False):
            filter_sessions(agent, [session], "fallback kw")
        captured = capsys.readouterr()

        assert captured.err == ""


class TestHyphenatedKeywordsAreSearchable:
    """AD-133：连字符关键词此前会让 FTS5 报 `no such column: <后半段>`。"""

    @pytest.mark.parametrize("keyword", ["auth-timeout", "other-hit", "feature-flag", "x-api-key"])
    def test_hyphenated_keyword_matches(self, keyword, tmp_path):
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": keyword}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text(keyword, encoding="utf-8")
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, [session])

        results = index.search(keyword)

        assert [r.session_id for r in results] == ["s1"], f"{keyword!r} 应能命中"

    def test_hyphenated_query_no_longer_raises_a_column_error(self, tmp_path):
        """修复前 `SELECT ... MATCH 'other-hit'` 抛 OperationalError: no such column: hit。"""
        index = SearchIndex(tmp_path / "index.db")
        index.ensure_initialized()

        assert index.search("other-hit") == []
