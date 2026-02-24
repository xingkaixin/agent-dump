"""
测试 query_filter.py 模块
"""

from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.query_filter import QuerySpec, filter_sessions, parse_query


class DummyAgent(BaseAgent):
    """用于测试的简化 Agent"""

    def __init__(self, name: str = "codex", session_data: dict[str, dict] | None = None):
        super().__init__(name=name, display_name="Dummy")
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


class TestParseQuery:
    """测试 parse_query 函数"""

    def test_parse_none(self):
        result = parse_query(None, {"opencode", "codex", "kimi", "claudecode"})
        assert result is None

    def test_parse_keyword_only(self):
        result = parse_query("报错", {"opencode", "codex", "kimi", "claudecode"})
        assert result == QuerySpec(agent_names=None, keyword="报错")

    def test_parse_agent_scope(self):
        result = parse_query("codex,kimi:报错", {"opencode", "codex", "kimi", "claudecode"})
        assert result == QuerySpec(agent_names={"codex", "kimi"}, keyword="报错")

    def test_parse_agent_scope_with_alias_and_case(self):
        result = parse_query("ClAuDe:bug", {"opencode", "codex", "kimi", "claudecode"})
        assert result == QuerySpec(agent_names={"claudecode"}, keyword="bug")

    def test_parse_empty_query_raises(self):
        with pytest.raises(ValueError, match="查询条件不能为空"):
            parse_query("   ", {"opencode", "codex", "kimi", "claudecode"})

    def test_parse_empty_keyword_in_scope_raises(self):
        with pytest.raises(ValueError, match="查询关键词不能为空"):
            parse_query("codex:   ", {"opencode", "codex", "kimi", "claudecode"})

    def test_parse_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="未知 agent 名称"):
            parse_query("codex,unknown:bug", {"opencode", "codex", "kimi", "claudecode"})

    def test_parse_colon_ambiguity_treat_as_plain_keyword(self):
        result = parse_query("error:timeout", {"opencode", "codex", "kimi", "claudecode"})
        assert result == QuerySpec(agent_names=None, keyword="error:timeout")


class TestFilterSessions:
    """测试 filter_sessions 函数"""

    def test_filter_by_title(self, tmp_path):
        agent = DummyAgent(name="codex")
        session = make_session("s1", "修复报错会话", tmp_path / "s1.jsonl")
        session.source_path.write_text("no-hit")

        result = filter_sessions(agent, [session], "报错")
        assert result == [session]

    def test_filter_by_source_file(self, tmp_path):
        agent = DummyAgent(name="codex")
        session = make_session("s1", "普通标题", tmp_path / "s1.jsonl")
        session.source_path.write_text("this has fatal bug text")

        result = filter_sessions(agent, [session], "fatal")
        assert result == [session]

    def test_filter_fallback_to_session_data(self, tmp_path):
        missing_path = tmp_path / "missing.jsonl"
        session = make_session("s1", "普通标题", missing_path)
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {
                    "messages": [
                        {"parts": [{"type": "text", "text": "session-data-keyword"}]},
                    ]
                }
            },
        )

        result = filter_sessions(agent, [session], "session-data-keyword")
        assert result == [session]

    def test_filter_opencode_with_sql_match(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                title TEXT,
                time_created INTEGER,
                time_updated INTEGER,
                slug TEXT,
                directory TEXT,
                version INTEGER,
                summary_files TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            )
            """
        )

        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Normal title", 1, 1, "slug1", "/tmp", 1, None),
        )
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s2", "Another title", 1, 1, "slug2", "/tmp", 1, None),
        )
        cursor.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("m1", "s1", 1, json.dumps({"role": "user", "content": "Fatal issue"})),
        )
        cursor.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            ("p1", "m1", 1, json.dumps({"type": "text", "text": "关键字命中"})),
        )
        conn.commit()
        conn.close()

        agent = OpenCodeAgent()
        agent.db_path = db_path
        sessions = [
            make_session("s1", "Normal title", db_path),
            make_session("s2", "Another title", db_path),
        ]

        result = filter_sessions(agent, sessions, "fatal")
        assert [s.id for s in result] == ["s1"]

    def test_filter_opencode_with_sql_no_match(self, tmp_path):
        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                title TEXT,
                time_created INTEGER,
                time_updated INTEGER,
                slug TEXT,
                directory TEXT,
                version INTEGER,
                summary_files TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            )
            """
        )
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Normal title", 1, 1, "slug1", "/tmp", 1, None),
        )
        conn.commit()
        conn.close()

        agent = OpenCodeAgent()
        agent.db_path = db_path
        sessions = [make_session("s1", "Normal title", db_path)]

        result = filter_sessions(agent, sessions, "missing-keyword")
        assert result == []
