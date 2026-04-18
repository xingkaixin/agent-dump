"""Tests for search_index.py module."""

from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.search_index import (
    SearchIndex,
    SearchResult,
    _build_fts_query,
    _extract_session_searchable_text,
    _extract_source_mtime,
    _has_cjk,
    _has_fts5,
    _select_fts_table,
    _serialize_for_search,
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


class TestExtractSourceMtime:
    def test_file_mtime(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("hello")
        mtime = _extract_source_mtime(file_path)
        assert mtime > 0

    def test_directory_max_mtime(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("a")
        mtime = _extract_source_mtime(tmp_path)
        assert mtime > 0

    def test_nonexistent_returns_zero(self, tmp_path):
        assert _extract_source_mtime(tmp_path / "missing") == 0.0


class TestExtractSessionSearchableText:
    def test_extracts_text_parts(self):
        agent = DummyAgent(session_data={
            "s1": {
                "messages": [
                    {"role": "user", "parts": [{"type": "text", "text": "Hello world"}]},
                    {"role": "assistant", "parts": [{"type": "text", "text": "Hi there"}]},
                ]
            }
        })
        session = make_session("s1", "Test", Path("/tmp/s1.jsonl"))
        text = _extract_session_searchable_text(agent, session)
        assert "Hello world" in text
        assert "Hi there" in text

    def test_extracts_reasoning(self):
        agent = DummyAgent(session_data={
            "s1": {
                "messages": [
                    {"role": "assistant", "parts": [{"type": "reasoning", "text": "Let me think"}]},
                ]
            }
        })
        session = make_session("s1", "Test", Path("/tmp/s1.jsonl"))
        text = _extract_session_searchable_text(agent, session)
        assert "Let me think" in text

    def test_extracts_tool_state(self):
        agent = DummyAgent(session_data={
            "s1": {
                "messages": [
                    {"role": "assistant", "parts": [
                        {"type": "tool", "tool": "bash", "state": {
                            "arguments": {"command": "ls -la"},
                            "output": [{"type": "text", "text": "file1.txt"}],
                            "prompt": "run bash",
                        }}
                    ]}
                ]
            }
        })
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
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword hit"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        added, removed = index.update(agent, [session])
        assert added == 1
        assert removed == 0

        results = index.search("keyword")
        assert len(results) == 1
        assert results[0].session_id == "s1"
        assert results[0].title == "Test"

    def test_incremental_skips_unchanged(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        added, removed = index.update(agent, [session])
        assert added == 0
        assert removed == 0

    def test_incremental_detects_mtime_change(self, tmp_path):
        import time

        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "old"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        # Change data and update mtime
        agent._session_data["s1"]["messages"][0]["parts"][0]["text"] = "new keyword"
        time.sleep(0.01)
        session.source_path.write_text("new data")

        added, removed = index.update(agent, [session])
        assert added == 1

    def test_delete_stale_sessions(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}
        })
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
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "error timeout bug"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        results = index.search("error timeout")
        assert len(results) == 1

    def test_search_cjk(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "修复认证模块的问题"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        # Short CJK (2 chars) uses unicode61
        results = index.search("认证")
        assert len(results) == 1

        # Longer CJK (3+ chars) uses trigram
        results = index.search("修复问题")
        assert len(results) == 1

    def test_search_snippet(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "the quick brown fox jumps over the lazy dog"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])

        results = index.search("fox")
        assert len(results) == 1
        assert results[0].snippet is not None
        assert "fox" in results[0].snippet or "**fox**" in results[0].snippet

    def test_search_with_agent_filter(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent1 = DummyAgent(name="codex", session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "codex keyword"}]}]}
        })
        agent2 = DummyAgent(name="kimi", session_data={
            "s2": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "kimi keyword"}]}]}
        })
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
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        assert len(index.search("keyword")) == 1

        deleted = index.clear_agent("codex")
        assert deleted == 1
        assert len(index.search("keyword")) == 0

    def test_rebuild(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")

        index.update(agent, [session])
        count = index.rebuild(agent, [session])
        assert count == 1
        assert len(index.search("keyword")) == 1

    def test_get_stats(self, tmp_path):
        index = SearchIndex(tmp_path / "index.db")
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "keyword"}]}]}
        })
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
        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "indexed keyword"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("data")
        index.update(agent, [session])

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            results = filter_sessions(agent, [session], "indexed keyword")
            assert len(results) == 1

    def test_filter_sessions_fallback_when_index_fails(self, tmp_path):
        from agent_dump.query_filter import filter_sessions

        agent = DummyAgent(session_data={
            "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fallback keyword"}]}]}
        })
        session = make_session("s1", "Test", tmp_path / "s1.jsonl")
        session.source_path.write_text("fallback keyword")

        with mock.patch("agent_dump.query_filter.SearchIndex", side_effect=Exception("boom")):
            results = filter_sessions(agent, [session], "fallback keyword")
            assert len(results) == 1
