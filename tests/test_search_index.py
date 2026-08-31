"""Tests for search_index.py module."""

from datetime import datetime, timedelta, timezone
import gc
import os
from pathlib import Path
import sqlite3
import threading
import tracemalloc
from unittest import mock

import pytest

from agent_dump import search_index as search_index_module
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import print_recoverable_diagnostic
from agent_dump.i18n import Keys
from agent_dump.query_filter import QuerySpec, select_session_groups
from agent_dump.query_semantics import TextQuery, TextQueryMode
from agent_dump.search_index import (
    _INDEX_BATCH_SIZE,
    _INDEX_RETENTION_SECONDS,
    SearchIndex,
    _batched,
    _build_fts_query,
    _has_cjk,
    _has_fts5,
    _preprocess_for_unicode61,
    extract_session_searchable_text,
)
from agent_dump.session_data import (
    session_updated_signal as _session_updated_signal,
)
from agent_dump.text_safety import has_unsafe_line_characters


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

    def get_sessions(self, days: int | None = 7) -> list[Session]:
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


def query_sessions_by_keyword(
    agent: BaseAgent,
    sessions: list[Session],
    keyword: str,
    *,
    diagnostic_sink=None,
) -> list[Session]:
    matches = select_session_groups(
        [(agent, sessions)],
        QuerySpec(agent_names=None, keyword=keyword, project_path=None, roles=None, limit=None),
        diagnostic_sink=diagnostic_sink,
    )
    return [match.session for match in matches]


class TestHasFts5:
    def test_detects_fts5_availability(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = __import__("sqlite3").connect(db_path)
        result = _has_fts5(conn)
        conn.close()
        assert isinstance(result, bool)

    def test_requires_trigram_tokenizer(self) -> None:
        conn = mock.MagicMock(spec=sqlite3.Connection)
        conn.execute.side_effect = sqlite3.OperationalError("no such tokenizer: trigram")

        assert _has_fts5(conn) is False
        assert "trigram" in conn.execute.call_args.args[0]


def test_content_version_refreshes_unchanged_legacy_tool_sessions(tmp_path):
    session = make_session("tool-session", "Tool session", tmp_path / "source.json")
    payload = {
        "messages": [
            {
                "role": "assistant",
                "parts": [{"type": "tool", "tool": "bash", "state": {"input": {"command": "quartz"}}}],
            }
        ]
    }
    agent = DummyAgent(session_data={session.id: payload})
    db_path = tmp_path / "index.db"
    index = SearchIndex(db_path)
    with mock.patch.object(search_index_module, "extract_session_searchable_text", return_value=""):
        assert index.update(agent, [session]) == (1, 0)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
    finally:
        conn.close()

    refreshed = SearchIndex(db_path)
    assert refreshed.update(agent, [session]) == (1, 0)
    assert [result.session_id for result in refreshed.search("quartz")] == [session.id]
    assert refreshed.update(agent, [session]) == (0, 0)


@pytest.mark.parametrize("reverse_providers", [False, True])
@pytest.mark.parametrize("limit", [1, None])
def test_cross_provider_ranking_is_stable_from_the_first_search(tmp_path, reverse_providers, limit):
    strong = make_session("strong", "Record", tmp_path / "strong.json")
    weak = make_session("weak", "Record", tmp_path / "weak.json")
    background = [make_session(f"background-{i}", "Record", tmp_path / f"bg-{i}.json") for i in range(50)]
    alpha = DummyAgent("alpha", {strong.id: {"messages": [{"role": "user", "content": "quartz " * 20}]}})
    beta = DummyAgent(
        "beta",
        {
            session.id: {
                "messages": [{"role": "user", "content": "quartz" if session is weak else "unrelated background text"}]
            }
            for session in [weak, *background]
        },
    )
    groups = [(alpha, [strong]), (beta, [weak, *background])]
    if reverse_providers:
        groups.reverse()
    spec = QuerySpec(None, "quartz", None, None, limit, TextQueryMode.SEARCH_TERMS)
    index = SearchIndex(tmp_path / "index.db")

    cold = select_session_groups(groups, spec, search_index=index)
    warm = select_session_groups(list(reversed(groups)), spec, search_index=index)

    expected = [("alpha", "strong")] if limit == 1 else [("alpha", "strong"), ("beta", "weak")]
    assert [(match.agent.name, match.session.id) for match in cold] == expected
    assert [(match.agent.name, match.session.id) for match in warm] == expected
    assert [match.rank for match in cold] == pytest.approx([match.rank for match in warm])


class TestHasCjk:
    def test_detects_chinese(self):
        assert _has_cjk("中文") is True

    def test_no_cjk_in_ascii(self):
        assert _has_cjk("hello world") is False

    def test_mixed(self):
        assert _has_cjk("hello中文") is True


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

    def test_split_cjk_keeps_each_user_term_as_one_phrase(self):
        query = TextQuery.parse("认证 超时", TextQueryMode.SEARCH_TERMS)

        assert _build_fts_query(query, split_cjk=True) == '"认 证" "超 时"'


class TestSessionUpdatedSignal:
    def test_signal_uses_updated_at(self, tmp_path):
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")

        assert _session_updated_signal(DummyAgent(), session) == (
            session.updated_at.replace(tzinfo=timezone.utc).isoformat(timespec="microseconds"),
            (),
            session.title,
        )

    def test_related_paths_are_recorded_independently(self, tmp_path):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        context_file = session_dir / "context.jsonl"
        context_file.write_text("context")
        wire_file = session_dir / "wire.jsonl"
        wire_file.write_text("wire")
        session = make_session("s1", "Test", session_dir)
        agent = DummyAgent()

        with mock.patch.object(agent, "get_session_change_sources", return_value=(context_file, wire_file)):
            before = _session_updated_signal(agent, session)
            wire_stat = wire_file.stat()
            os.utime(wire_file, ns=(wire_stat.st_atime_ns, wire_stat.st_mtime_ns + 500_000))
            after = _session_updated_signal(agent, session)

        assert before != after
        assert [source[0] for source in after[1]] == [str(context_file), str(wire_file)]

    def test_missing_related_paths_remain_part_of_the_signature(self, tmp_path):
        session = make_session("s1", "Test", tmp_path / "session")
        agent = DummyAgent()
        missing = tmp_path / "missing.jsonl"

        with mock.patch.object(agent, "get_session_change_sources", return_value=(missing,)):
            signal = _session_updated_signal(agent, session)

        assert signal[1] == ((str(missing), None, None, None),)


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

    def test_missing_normalized_messages_does_not_read_raw_source(self, tmp_path):
        source = tmp_path / "session.jsonl"
        source.write_text('{"internal_metadata": "raw-only-keyword"}')
        agent = DummyAgent(session_data={})
        session = make_session("s1", "Test", source)

        assert extract_session_searchable_text(agent, session) is None


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
        assert agent.data_reads == 1
        assert agent.get_cached_session_data(session)["messages"][0]["role"] == "user"
        assert agent.data_reads == 2

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

    def test_title_update_does_not_reload_other_sessions(self, tmp_path: Path) -> None:
        index = SearchIndex(tmp_path / "index.db")
        sessions = [make_session(name, name, tmp_path / f"{name}.jsonl") for name in ("original", "unchanged")]
        agent = DummyAgent(session_data={session.id: {"messages": []} for session in sessions})
        assert index.update(agent, sessions) == (2, 0)

        sessions[0].title = "Rocket"

        assert index.update(agent, sessions) == (1, 0)
        assert agent.data_reads == 3
        assert [result.session_id for result in index.search("Rocket")] == ["original"]
        assert index.search("original") == []

    def test_incremental_detects_submillisecond_source_change(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "old"}]}]}}
        )
        source = tmp_path / "s1.jsonl"
        source.write_text("old", encoding="utf-8")
        initial_stat = source.stat()
        session = make_session("s1", "Test", source)

        with mock.patch.object(agent, "get_session_change_sources", return_value=(source,)):
            index.update(agent, [session])
            agent._session_data["s1"]["messages"][0]["parts"][0]["text"] = "new needle"
            os.utime(source, ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns + 500_000))
            added, removed = index.update(agent, [session])

        assert (added, removed) == (1, 0)
        assert [result.session_id for result in index.search("needle")] == ["s1"]
        assert index.search("old") == []

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

        index.update(agent, sessions, diagnostic_sink=print_recoverable_diagnostic)

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

        # 部分窗口只看到 s1 时，s2 仍是可复用的缓存，但不得进入当前搜索。
        added, removed = index.update(agent, [session1])
        assert (added, removed) == (0, 0)
        assert len(index.search("alpha")) == 1
        assert len(index.search("bravo")) == 1
        assert index.search("bravo", session_keys={("codex", "s1")}) == []

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

    def test_float_freshness_schema_is_rebuilt(self, tmp_path):
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE index_state (
                fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                session_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                updated_signal REAL NOT NULL,
                indexed_at REAL NOT NULL,
                session_updated_at REAL NOT NULL,
                session_created_at REAL NOT NULL,
                UNIQUE (agent, session_id)
            )
            """
        )
        conn.commit()
        conn.close()

        index = SearchIndex(db_path)
        index.ensure_initialized()
        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(index_state)")}
        finally:
            conn.close()

        assert "updated_signature" in columns
        assert "updated_signal" not in columns

    def test_narrow_update_cannot_evict_a_wide_search_window(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "old": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "historic"}]}]},
                "recent": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "current"}]}]},
            }
        )
        source = tmp_path / "sessions.jsonl"
        source.write_text("data")
        old = make_session("old", "Old", source)
        recent = make_session("recent", "Recent", source)

        index.update(agent, [old, recent])
        added, removed = index.update(agent, [recent])

        assert (added, removed) == (0, 0)
        assert [
            result.session_id
            for result in index.search(
                "historic",
                agent_names={"codex"},
                session_keys={("codex", "old"), ("codex", "recent")},
            )
        ] == ["old"]
        assert (
            index.search(
                "historic",
                agent_names={"codex"},
                session_keys={("codex", "recent")},
            )
            == []
        )

    def test_unseen_rows_expire_from_state_and_full_text_tables(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={"s1": {"messages": [{"role": "user", "content": "private retained needle"}]}})
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")

        with mock.patch("agent_dump.search_index.time.time", return_value=1_000.0):
            index.update(agent, [session])
        with mock.patch(
            "agent_dump.search_index.time.time",
            return_value=1_000.0 + _INDEX_RETENTION_SECONDS + 1,
        ):
            index.ensure_initialized()

        assert index.get_stats() == {}
        conn = sqlite3.connect(tmp_path / "index.db")
        try:
            assert conn.execute("SELECT COUNT(*) FROM sessions_fts").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM sessions_fts_trigram").fetchone()[0] == 0
        finally:
            conn.close()

    def test_unchanged_seen_rows_refresh_retention_without_reindexing(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={"s1": {"messages": [{"role": "user", "content": "still searchable"}]}})
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")

        with mock.patch("agent_dump.search_index.time.time", return_value=1_000.0):
            index.update(agent, [session])
        with mock.patch(
            "agent_dump.search_index.time.time",
            return_value=1_000.0 + _INDEX_RETENTION_SECONDS - 10,
        ):
            added, removed = index.update(agent, [session])
        with mock.patch(
            "agent_dump.search_index.time.time",
            return_value=1_000.0 + _INDEX_RETENTION_SECONDS + 10,
        ):
            results = index.search("searchable")

        assert (added, removed) == (0, 0)
        assert agent.data_reads == 1
        assert [result.session_id for result in results] == ["s1"]

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

    def test_search_terms_can_match_title_and_content(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "request timeout"}]}]}
            }
        )
        session = make_session("s1", "Auth incident", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        assert [result.session_id for result in index.search("auth timeout")] == ["s1"]

    @pytest.mark.parametrize(
        ("title", "query"),
        [
            ("İstanbul incident", "istanbul"),
            ("ıstanbul incident", "Istanbul"),
            ("Istanbul incident", "İstanbul"),
            ("istanbul incident", "ıstanbul"),
        ],
    )
    def test_search_matches_unicode_i_with_canonical_case_rules(self, tmp_path, title, query):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={"s1": {"messages": []}})
        session = make_session("s1", title, tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        assert [result.session_id for result in index.search(query)] == ["s1"]

    def test_keyword_phrase_normalizes_source_whitespace(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "auth\n  timeout"}]}]}
            }
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")
        index.update(agent, [session])

        query = TextQuery.parse("auth timeout", TextQueryMode.KEYWORD)

        assert [result.session_id for result in index.search(query)] == ["s1"]

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

        # 一个 CJK term 必须是连续字面量，不能退化成「每个汉字都出现过」
        results = index.search("修复问题")
        assert results == []

    def test_search_cjk_does_not_join_unrelated_characters(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "认知经过证明"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        assert index.search("认证") == []

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
        class TracedSearchIndex(SearchIndex):
            def __init__(self, db_path: Path) -> None:
                super().__init__(db_path)
                self.statements: list[str] = []

            def _get_connection(self) -> sqlite3.Connection:
                conn = super()._get_connection()
                conn.set_trace_callback(self.statements.append)
                return conn

        index = TracedSearchIndex(tmp_path / "index.db")
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
        assert not any("RETURNING" in statement for statement in index.statements)

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
        assert {statement.split(" WHERE ")[0] for statement in index.delete_statements} == {
            "DELETE FROM sessions_fts",
            "DELETE FROM sessions_fts_trigram",
        }, "两张表都必须被清空，否则另一张会留下孤儿行"
        assert all("rowid = " in statement for statement in index.delete_statements), (
            "UNINDEXED 列定位是全表扫描，clear 也必须走 rowid"
        )

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
            results = query_sessions_by_keyword(agent, [session], "indexed keyword")
            assert len(results) == 1

    def test_filter_sessions_fallback_when_index_fails(self, tmp_path, capsys):
        agent = DummyAgent(
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fallback keyword"}]}]}
            }
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("fallback keyword")
        poison = "value\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        agent.display_name = poison

        with mock.patch("agent_dump.query_filter.SearchIndex", side_effect=Exception(f"boom {poison}")):
            results = query_sessions_by_keyword(
                agent,
                [session],
                "fallback keyword",
                diagnostic_sink=print_recoverable_diagnostic,
            )
            assert len(results) == 1

        warning = capsys.readouterr().err.rstrip("\n")
        assert not has_unsafe_line_characters(warning)
        assert "FORGED" in warning


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


def _fts_rowid_of(db_path: Path, agent: str, session_id: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT fts_rowid FROM index_state WHERE agent = ? AND session_id = ?",
            (agent, session_id),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"{agent}/{session_id} 没有 index_state 行"
    return row[0]


class TestBatched:
    def test_splits_into_fixed_size_slices(self):
        assert list(_batched([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_empty_input_yields_nothing(self):
        assert list(_batched([], 4)) == []


def _spy_on_fts_deletes(monkeypatch) -> list[list[int]]:
    """记录每次 FTS 删除的 rowid，同时保留真实删除。

    纯打桩会让紧随其后的同 rowid 插入撞上 FTS5 唯一约束，反而测不到删除语义。
    """
    calls: list[list[int]] = []
    real = search_index_module._delete_fts_rows

    def spy(conn, rowids):
        calls.append(list(rowids))
        real(conn, rowids)

    monkeypatch.setattr("agent_dump.search_index._delete_fts_rows", spy)
    return calls


class TestIndexBuildAvoidsRedundantDeletes:
    """AD-120：FTS5 表里 session_id 是 UNINDEXED，空删除会全表扫描。"""

    def test_first_build_issues_no_delete(self, tmp_path, monkeypatch):
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        sessions = [make_session(f"s{i}", f"标题{i}", source) for i in range(5)]
        agent = DummyAgent(session_data={s.id: {"messages": []} for s in sessions})

        calls = _spy_on_fts_deletes(monkeypatch)

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

        indexed_rowid = _fts_rowid_of(tmp_path / "index.db", "codex", "s1")

        calls = _spy_on_fts_deletes(monkeypatch)
        # updated signature 取 session.updated_at 与 provider-owned change sources，
        # 不看 source_path，所以必须推进 updated_at 才算「有变更」
        index.update(agent, [_touched(session)])

        assert calls == [[indexed_rowid]], "已索引过的会话更新时必须按稳定 rowid 删掉旧行"

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


class TestStableFtsRowid:
    """AD-153：index_state 持有的 rowid 是两张 FTS 表的唯一定位方式。"""

    def test_rowid_is_stable_across_reindex(self, tmp_path):
        db_path = tmp_path / "index.db"
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        session = make_session("s1", "Test", source)
        agent = DummyAgent(session_data={"s1": {"messages": [{"role": "user", "content": "keyword"}]}})

        index = SearchIndex(db_path)
        index.update(agent, [session])
        first = _fts_rowid_of(db_path, "codex", "s1")
        index.update(agent, [_touched(session)])

        assert _fts_rowid_of(db_path, "codex", "s1") == first

    def test_same_session_id_across_agents_gets_distinct_rowids(self, tmp_path):
        db_path = tmp_path / "index.db"
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        session = make_session("shared", "Test", source)
        index = SearchIndex(db_path)

        for name, body in (("codex", "alpha"), ("claudecode", "bravo")):
            agent = DummyAgent(name=name, session_data={"shared": {"messages": [{"role": "user", "content": body}]}})
            index.update(agent, [session])

        codex_rowid = _fts_rowid_of(db_path, "codex", "shared")
        claude_rowid = _fts_rowid_of(db_path, "claudecode", "shared")
        assert codex_rowid != claude_rowid, "rowid 必须全局唯一，否则两个 Provider 会互相覆盖 FTS 行"
        assert {result.agent_name for result in index.search("alpha")} == {"codex"}
        assert {result.agent_name for result in index.search("bravo")} == {"claudecode"}

    def test_all_three_tables_share_one_row_per_session(self, tmp_path):
        db_path = tmp_path / "index.db"
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        keep = make_session("keep", "Keep", source)
        drop = make_session("drop", "Drop", source)
        agent = DummyAgent(
            session_data={
                "keep": {"messages": [{"role": "user", "content": "alpha"}]},
                "drop": {"messages": [{"role": "user", "content": "bravo"}]},
            }
        )

        index = SearchIndex(db_path)
        index.update(agent, [keep, drop])
        index.rebuild(agent, [_touched(keep)])

        conn = sqlite3.connect(db_path)
        try:
            state_rowids = {row[0] for row in conn.execute("SELECT fts_rowid FROM index_state")}
            for table in ("sessions_fts", "sessions_fts_trigram"):
                fts_rowids = {row[0] for row in conn.execute(f"SELECT rowid FROM {table}")}
                assert fts_rowids == state_rowids, f"{table} 与 index_state 出现孤儿行"
        finally:
            conn.close()
        assert len(index.search("bravo")) == 0, "显式重建必须一并删除旧会话的 FTS 行"

    def test_reused_rowid_cannot_leak_a_deleted_session(self, tmp_path):
        """AUTOINCREMENT 防止删掉末尾行后新会话拿到同一个 rowid。"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        first = make_session("first", "First", source)
        second = make_session("second", "Second", source)
        agent = DummyAgent(
            session_data={
                "first": {"messages": [{"role": "user", "content": "alpha"}]},
                "second": {"messages": [{"role": "user", "content": "bravo"}]},
            }
        )

        index = SearchIndex(db_path)
        index.update(agent, [first])
        removed_rowid = _fts_rowid_of(db_path, "codex", "first")
        index.clear_agent(agent.name)
        index.update(agent, [second])

        assert _fts_rowid_of(db_path, "codex", "second") != removed_rowid

    def test_full_reindex_cost_grows_near_linearly(self, tmp_path):
        """按 UNINDEXED 列删除要全表扫内容行，全量更新退化为 O(N²)；按 rowid 是 O(N log N)。

        用 VDBE 指令数而不是墙钟时间：同样的 SQL 与数据下它是确定值，不会因 CI
        机器负载抖动而 flaky。
        """

        def steps_to_reindex_all(index_size: int) -> int:
            db_path = tmp_path / f"index-{index_size}.db"
            source = tmp_path / "s.jsonl"
            source.write_text("x", encoding="utf-8")
            sessions = [make_session(f"s{i}", f"Title {i}", source) for i in range(index_size)]
            agent = DummyAgent(
                session_data={s.id: {"messages": [{"role": "user", "content": f"body {s.id}"}]} for s in sessions}
            )

            counted: list[int] = [0]

            class CountingSearchIndex(SearchIndex):
                def _get_connection(self):
                    conn = super()._get_connection()
                    conn.set_progress_handler(lambda: counted.__setitem__(0, counted[0] + 1) or 0, 100)
                    return conn

            index = CountingSearchIndex(db_path)
            index.update(agent, sessions)
            counted[0] = 0
            index.update(agent, [_touched(session) for session in sessions])
            return counted[0]

        small = steps_to_reindex_all(40)
        large = steps_to_reindex_all(320)

        # 规模放大 8 倍：O(N log N) 约 9.5 倍，O(N²) 约 64 倍
        assert large < small * 20, f"全量重索引成本超线性放大（{small} → {large}），删除仍在全表扫描"

    def test_legacy_composite_key_schema_is_rebuilt(self, tmp_path):
        """AD-120 的 (agent, session_id) 主键库没有 rowid 列，必须整表重建。"""
        db_path = tmp_path / "index.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE index_state (
                agent TEXT NOT NULL,
                session_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                updated_signal REAL NOT NULL,
                indexed_at REAL NOT NULL,
                PRIMARY KEY (agent, session_id)
            )
            """
        )
        conn.execute("INSERT INTO index_state VALUES ('codex', 'stale', '/gone', 1.0, 1.0)")
        conn.commit()
        conn.close()

        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        session = make_session("s1", "Test", source)
        agent = DummyAgent(session_data={"s1": {"messages": [{"role": "user", "content": "keyword"}]}})

        index = SearchIndex(db_path)
        added, removed = index.update(agent, [session])

        assert (added, removed) == (1, 0), "旧 schema 被重建后不应把已消失的旧行算作删除"
        assert len(index.search("keyword")) == 1
        assert _fts_rowid_of(db_path, "codex", "s1") > 0


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

    def test_full_payload_memory_does_not_accumulate_across_batches(self, tmp_path) -> None:
        payload_size = 256 * 1024
        total = _INDEX_BATCH_SIZE * 3 + 4
        source = tmp_path / "s.jsonl"
        source.write_text("x", encoding="utf-8")
        sessions = [make_session(f"s{index}", f"Title {index}", source) for index in range(total)]

        class LargePayloadAgent(DummyAgent):
            def get_session_data(self, session: Session) -> dict[str, object]:
                self.data_reads += 1
                return {
                    "padding": bytearray(payload_size),
                    "messages": [{"role": "user", "content": f"body {session.id}"}],
                }

        agent = LargePayloadAgent()
        index = SearchIndex(tmp_path / "index.db")

        gc.collect()
        tracemalloc.start()
        baseline, _ = tracemalloc.get_traced_memory()
        added, _ = index.update(agent, sessions)
        gc.collect()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert added == total
        assert agent.data_reads == total
        assert not agent._session_data_cache._entries
        assert current - baseline < payload_size * 8
        assert peak - baseline < payload_size * (_INDEX_BATCH_SIZE + 16)


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

    def test_returns_none_when_per_session_jsonl_parse_fails(self, tmp_path):
        source = tmp_path / "session.jsonl"
        source.write_text('{"internal_metadata": "raw-only-keyword"}', encoding="utf-8")
        session = make_session("s1", "Test", source)

        assert extract_session_searchable_text(FailingAgent(), session) is None

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

    def test_failed_refresh_removes_stale_searchable_content(self, tmp_path):
        source = tmp_path / "session.jsonl"
        source.write_text("source", encoding="utf-8")
        session = make_session("s1", "Unrelated title", source)
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "content": "stale-keyword"}]}},
        )
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, [session])

        session.updated_at += timedelta(seconds=1)
        with mock.patch.object(agent, "get_session_data", side_effect=OSError("transient read failure")):
            added, _ = index.update(agent, [session])

        assert added == 0
        assert index.search("stale-keyword") == []
        assert index.get_stats() == {}

        agent._session_data["s1"] = {"messages": [{"role": "user", "content": "fresh-keyword"}]}
        added, _ = index.update(agent, [session])

        assert added == 1
        assert [result.session_id for result in index.search("fresh-keyword")] == ["s1"]

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

        index.update(
            FailingAgent(name="opencode"),
            sessions,
            diagnostic_sink=print_recoverable_diagnostic,
        )
        captured = capsys.readouterr()

        assert "2 个会话读取失败" in captured.err


class TestFallbackSearchHandlesUnreadableSessions:
    """AD-121：query_filter 的兜底匹配也要能吃 None。"""

    def test_unreadable_session_is_skipped_not_crashed(self, tmp_path):
        from agent_dump.query_filter import _fallback_search_matches, _SearchRuntime

        source = tmp_path / "session.jsonl"
        source.write_text('{"internal_metadata": "keyword"}', encoding="utf-8")
        sessions = [make_session("s1", "无关标题", source)]

        diagnostics = []
        runtime = _SearchRuntime(diagnostic_sink=diagnostics.append)

        assert _fallback_search_matches(FailingAgent(name="opencode"), sessions, "keyword", runtime) == []
        assert diagnostics[0].fields["uri"] == "opencode://s1"


class TestIndexFailureIsReported:
    """AD-133：索引出错必须说出来，而不是与「没有索引」混为一谈。"""

    def test_index_error_is_returned_as_a_structured_diagnostic(self, tmp_path, capsys):
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "content": "fallback kw"}]}},
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        diagnostics = []

        with mock.patch("agent_dump.query_filter.SearchIndex", side_effect=sqlite3.DatabaseError("db is locked")):
            results = query_sessions_by_keyword(
                agent,
                [session],
                "fallback kw",
                diagnostic_sink=diagnostics.append,
            )

        assert len(results) == 1
        assert diagnostics[0].message_key == Keys.WARN_INDEX_UNUSABLE
        assert diagnostics[0].fields["error_type"] == "DatabaseError"
        assert capsys.readouterr().err == ""

    def test_index_error_warns_and_still_falls_back(self, tmp_path, capsys):
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fallback kw"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("fallback kw", encoding="utf-8")

        with mock.patch("agent_dump.query_filter.SearchIndex", side_effect=sqlite3.DatabaseError("db is locked")):
            results = query_sessions_by_keyword(
                agent,
                [session],
                "fallback kw",
                diagnostic_sink=print_recoverable_diagnostic,
            )
        captured = capsys.readouterr()

        assert len(results) == 1, "退回文件扫描仍应给出结果"
        assert "搜索索引不可用" in captured.err
        assert "DatabaseError" in captured.err
        assert "--reindex" in captured.err

    def test_missing_fts5_support_is_not_reported_as_an_error(self, tmp_path, capsys):
        """没编译 FTS5 是正常状态，不该每次查询都刷告警。"""
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fallback kw"}]}]}}
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("fallback kw", encoding="utf-8")

        with mock.patch.object(SearchIndex, "is_available", new_callable=mock.PropertyMock, return_value=False):
            query_sessions_by_keyword(agent, [session], "fallback kw")
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

    @pytest.mark.parametrize("keyword", ["*", "a*", '"hi"'])
    def test_short_or_operator_like_terms_use_literal_scan(self, keyword, tmp_path):
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "content": f"literal {keyword} value"}]}},
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("{}", encoding="utf-8")
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, [session])

        assert [result.session_id for result in index.search(keyword)] == ["s1"]


class TestSearchLimitPushdown:
    """AD-154：明确要 top-L 时不该把 M 条命中全部搬进 Python。"""

    @staticmethod
    def _seed(tmp_path, count: int, *, agent_name: str = "codex", minute_offset: int = 0):
        source = tmp_path / f"{agent_name}.jsonl"
        source.write_text("x", encoding="utf-8")
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sessions = [
            Session(
                id=f"{agent_name}-{i}",
                title=f"session {i}",
                created_at=base + timedelta(minutes=i + minute_offset),
                updated_at=base + timedelta(minutes=i + minute_offset),
                source_path=source,
                metadata={},
            )
            for i in range(count)
        ]
        agent = DummyAgent(
            name=agent_name,
            session_data={s.id: {"messages": [{"role": "user", "content": "common keyword"}]} for s in sessions},
        )
        return agent, sessions

    def test_limit_returns_only_the_top_l(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 50)
        index.update(agent, sessions)

        assert len(index.search("common", limit=10)) == 10

    def test_no_limit_still_returns_every_hit(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 50)
        index.update(agent, sessions)

        assert len(index.search("common")) == 50

    def test_limited_results_are_the_prefix_of_the_unlimited_ones(self, tmp_path):
        """下推不得改变顺序，否则 top-L 与全量排序的前 L 会是两组不同结果。"""
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 40)
        index.update(agent, sessions)

        everything = index.search("common")
        top = index.search("common", limit=7)

        assert [r.session_id for r in top] == [r.session_id for r in everything[:7]]

    def test_tied_rank_order_is_stable_across_repeated_searches(self, tmp_path):
        """全部命中 rank 相同，顺序只能由 updated/created/agent/session 决定。"""
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 30)
        index.update(agent, sessions)

        first = [r.session_id for r in index.search("common", limit=10)]
        second = [r.session_id for r in index.search("common", limit=10)]

        assert first == second
        assert len(set(first)) == 10

    def test_more_recent_sessions_win_a_rank_tie(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 20)
        index.update(agent, sessions)

        top = index.search("common", limit=5)
        updated_at_by_id = {s.id: s.updated_at for s in sessions}
        ordered = [updated_at_by_id[r.session_id] for r in top]

        assert ordered == sorted(ordered, reverse=True), "平局时应按 updated_at 由新到旧"

    def test_limit_applies_per_agent_filter(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        codex_agent, codex_sessions = self._seed(tmp_path, 20, agent_name="codex")
        claude_agent, claude_sessions = self._seed(tmp_path, 20, agent_name="claudecode", minute_offset=100)
        index.update(codex_agent, codex_sessions)
        index.update(claude_agent, claude_sessions)

        scoped = index.search("common", agent_names={"codex"}, limit=5)

        assert len(scoped) == 5
        assert {r.agent_name for r in scoped} == {"codex"}

    def test_session_scope_applies_before_limit(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 5)
        index.update(agent, sessions)

        scoped = index.search(
            "common",
            agent_names={agent.name},
            session_keys={(agent.name, sessions[0].id)},
            limit=1,
        )

        assert [result.session_id for result in scoped] == [sessions[0].id]

    def test_literal_session_scope_is_applied_by_sql(self, tmp_path, monkeypatch) -> None:
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 5)
        index.update(agent, sessions)
        statements: list[str] = []
        original_get_connection = index._get_connection

        def traced_connection() -> sqlite3.Connection:
            connection = original_get_connection()
            connection.set_trace_callback(statements.append)
            return connection

        monkeypatch.setattr(index, "_get_connection", traced_connection)

        scoped = index.search("c", session_keys={(agent.name, sessions[0].id)})

        assert [result.session_id for result in scoped] == [sessions[0].id]
        literal_selects = [
            statement.lower()
            for statement in statements
            if "sessions_fts_trigram" in statement.lower() and "index_state" in statement.lower()
        ]
        assert literal_selects
        assert all("s.session_id" in statement.split("where", 1)[-1] for statement in literal_selects)

    def test_limit_larger_than_the_hit_count_returns_everything(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent, sessions = self._seed(tmp_path, 3)
        index.update(agent, sessions)

        assert len(index.search("common", limit=100)) == 3

    @pytest.mark.parametrize(
        ("keyword", "content"),
        [("x", "literal x value"), ("认证", "修复认证模块")],
    )
    def test_limited_search_streams_database_rows(self, keyword, content, tmp_path, monkeypatch):
        class FetchallGuardCursor:
            def __init__(self, cursor):
                self._cursor = cursor

            def __iter__(self):
                return iter(self._cursor)

            def fetchall(self):
                raise AssertionError("limited search must not materialize every database row")

        class FetchallGuardConnection:
            def __init__(self, connection):
                self._connection = connection

            def __getattr__(self, name):
                return getattr(self._connection, name)

            def execute(self, sql, params=()):
                cursor = self._connection.execute(sql, params)
                return FetchallGuardCursor(cursor) if "SELECT f.agent_name" in sql else cursor

        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(
            session_data={"s1": {"messages": [{"role": "user", "content": content}]}},
        )
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data", encoding="utf-8")
        index.update(agent, [session])
        original_get_connection = index._get_connection
        monkeypatch.setattr(
            index,
            "_get_connection",
            lambda: FetchallGuardConnection(original_get_connection()),
        )

        assert [result.session_id for result in index.search(keyword, limit=1)] == ["s1"]

    def test_literal_limit_keeps_python_memory_proportional_to_limit(self, tmp_path):
        count = 96
        body_size = 64 * 1024
        max_peak_bytes = 2 * 1024 * 1024
        body = "x " + "z" * body_size
        agent, sessions = self._seed(tmp_path, count)
        agent._session_data = {session.id: {"messages": [{"role": "user", "content": body}]} for session in sessions}
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, sessions)

        gc.collect()
        tracemalloc.start()
        baseline, _ = tracemalloc.get_traced_memory()
        results = index.search("x", limit=5)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert len(results) == 5
        assert peak - baseline < max_peak_bytes
