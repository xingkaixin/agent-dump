"""
测试 query_filter.py 模块
"""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.query_filter import (
    QuerySpec,
    SearchSessionMatch,
    extract_session_project_path,
    filter_sessions,
    filter_sessions_by_query,
    limit_search_matches,
    limit_query_matches,
    parse_query,
    parse_query_uri,
    search_sessions_by_query,
)
from agent_dump.search_index import SearchResult


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


def make_query_spec(
    *,
    agent_names: set[str] | None = None,
    keyword: str | None = None,
    project_path: Path | None = None,
    roles: set[str] | None = None,
    limit: int | None = None,
) -> QuerySpec:
    return QuerySpec(
        agent_names=agent_names,
        keyword=keyword,
        project_path=project_path,
        roles=roles,
        limit=limit,
    )


class TestParseQuery:
    """测试 parse_query 函数"""

    def test_parse_none(self):
        result = parse_query(None, {"opencode", "codex", "kimi", "claudecode"})
        assert result is None

    def test_parse_keyword_only(self):
        result = parse_query("报错", {"opencode", "codex", "kimi", "claudecode"})
        assert result == make_query_spec(keyword="报错")

    def test_parse_agent_scope(self):
        result = parse_query("codex,kimi:报错", {"opencode", "codex", "kimi", "claudecode"})
        assert result == make_query_spec(agent_names={"codex", "kimi"}, keyword="报错")

    def test_parse_agent_scope_with_alias_and_case(self):
        result = parse_query("ClAuDe:bug", {"opencode", "codex", "kimi", "claudecode"})
        assert result == make_query_spec(agent_names={"claudecode"}, keyword="bug")

    def test_parse_structured_terms(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = parse_query(
            "bug provider:codex,claude role:User,assistant path:. limit:20",
            {"opencode", "codex", "kimi", "claudecode"},
        )
        assert result == make_query_spec(
            agent_names={"codex", "claudecode"},
            keyword="bug",
            project_path=tmp_path.resolve(),
            roles={"user", "assistant"},
            limit=20,
        )

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
        assert result == make_query_spec(keyword="error:timeout")

    def test_parse_unknown_structured_key_raises(self):
        with pytest.raises(ValueError, match="未知查询字段"):
            parse_query("bug provider:codex foo:bar", {"opencode", "codex", "kimi", "claudecode"})

    def test_parse_invalid_limit_raises(self):
        with pytest.raises(ValueError, match="limit 必须是正整数"):
            parse_query("role:user limit:0 bug", {"opencode", "codex", "kimi", "claudecode"})


class TestParseQueryUri:
    def test_parse_relative_dot_path(self, tmp_path):
        result = parse_query_uri(
            "agents://.?q=refactor&providers=codex,claude&roles=user&limit=2",
            {"opencode", "codex", "kimi", "claudecode"},
            cwd=tmp_path,
        )
        assert result == make_query_spec(
            agent_names={"codex", "claudecode"},
            keyword="refactor",
            project_path=tmp_path.resolve(),
            roles={"user"},
            limit=2,
        )

    def test_parse_home_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = parse_query_uri(
            "agents://~/repo",
            {"opencode", "codex", "kimi", "claudecode"},
            cwd=tmp_path / "work",
        )
        assert result == make_query_spec(project_path=(tmp_path / "repo").resolve())

    def test_parse_absolute_path(self):
        result = parse_query_uri(
            "agents:///tmp/project?q=bug",
            {"opencode", "codex", "kimi", "claudecode"},
            cwd=Path("/work"),
        )
        assert result == make_query_spec(keyword="bug", project_path=Path("/tmp/project").resolve(strict=False))

    def test_parse_empty_providers_raises(self):
        with pytest.raises(ValueError, match="providers 不能为空"):
            parse_query_uri("agents://.?providers=", {"opencode", "codex"}, cwd=Path("/work"))

    def test_parse_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="未知 agent 名称"):
            parse_query_uri("agents://.?providers=codex,unknown", {"opencode", "codex"}, cwd=Path("/work"))

    def test_parse_empty_roles_raises(self):
        with pytest.raises(ValueError, match="roles 不能为空"):
            parse_query_uri("agents://.?roles=", {"opencode", "codex"}, cwd=Path("/work"))

    def test_parse_invalid_limit_raises(self):
        with pytest.raises(ValueError, match="limit 必须是正整数"):
            parse_query_uri("agents://.?limit=bad", {"opencode", "codex"}, cwd=Path("/work"))

    def test_parse_non_agents_uri_returns_none(self):
        assert parse_query_uri("codex://session-1", {"codex"}, cwd=Path("/work")) is None


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

    def test_filter_does_not_fallback_when_searchable_source_exists(self, tmp_path):
        source_path = tmp_path / "s1.jsonl"
        source_path.write_text("no-hit", encoding="utf-8")
        session = make_session("s1", "普通标题", source_path)
        agent = DummyAgent(
            name="codex",
            session_data={"s1": {"messages": [{"parts": [{"type": "text", "text": "fatal"}]}]}},
        )

        with (
            mock.patch.object(agent, "get_session_data", wraps=agent.get_session_data) as mock_get_session_data,
            mock.patch("agent_dump.query_filter._try_indexed_search", return_value=None),
        ):
            result = filter_sessions(agent, [session], "fatal")

        assert result == []
        mock_get_session_data.assert_not_called()

    def test_filter_directory_prefers_wire_file(self, tmp_path):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        (session_dir / "wire.jsonl").write_text("wire-hit", encoding="utf-8")
        (session_dir / "other.jsonl").write_text("other-hit", encoding="utf-8")
        session = make_session("s1", "普通标题", session_dir)
        agent = DummyAgent(name="kimi")

        result = filter_sessions(agent, [session], "wire-hit")
        assert result == [session]

        result = filter_sessions(agent, [session], "other-hit")
        assert result == []

    def test_filter_binary_like_source_falls_back_to_session_data(self, tmp_path):
        source_path = tmp_path / "state.vscdb"
        source_path.write_bytes(b"sqlite data")
        session = make_session("s1", "普通标题", source_path)
        agent = DummyAgent(
            name="cursor",
            session_data={"s1": {"messages": [{"parts": [{"type": "text", "text": "fatal"}]}]}},
        )

        with mock.patch.object(agent, "get_session_data", wraps=agent.get_session_data) as mock_get_session_data:
            result = filter_sessions(agent, [session], "fatal")

        assert result == [session]
        mock_get_session_data.assert_called_once_with(session)

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


class TestFilterSessionsByQuery:
    def test_path_scope_matches_equal_parent_and_child(self, tmp_path):
        agent = DummyAgent(name="codex")
        repo_root = tmp_path / "repo"
        subdir = repo_root / "src"
        equal = make_session("s1", "equal", tmp_path / "s1.jsonl")
        equal.metadata = {"cwd": str(repo_root)}
        parent = make_session("s2", "parent", tmp_path / "s2.jsonl")
        parent.metadata = {"cwd": str(subdir)}
        child = make_session("s3", "child", tmp_path / "s3.jsonl")
        child.metadata = {"cwd": str(tmp_path)}

        spec = make_query_spec(project_path=repo_root)
        result = filter_sessions_by_query(agent, [equal, parent, child], spec)
        assert [session.id for session in result] == ["s1", "s2", "s3"]

    def test_path_scope_excludes_same_prefix_non_descendant(self, tmp_path):
        agent = DummyAgent(name="codex")
        repo_root = tmp_path / "repo"
        session = make_session("s1", "prefix", tmp_path / "s1.jsonl")
        session.metadata = {"cwd": str(tmp_path / "repo-other")}

        spec = make_query_spec(project_path=repo_root)
        assert filter_sessions_by_query(agent, [session], spec) == []

    def test_path_scope_excludes_session_without_project_path(self, tmp_path):
        agent = DummyAgent(name="cursor")
        session = make_session("s1", "no path", tmp_path / "s1.jsonl")
        spec = make_query_spec(project_path=tmp_path / "repo")

        assert filter_sessions_by_query(agent, [session], spec) == []

    def test_combines_path_scope_and_keyword(self, tmp_path):
        agent = DummyAgent(name="codex")
        session = make_session("s1", "refactor api", tmp_path / "s1.jsonl")
        session.metadata = {"cwd": str(tmp_path / "repo")}
        session.source_path.write_text("contains refactor", encoding="utf-8")
        other = make_session("s2", "refactor api", tmp_path / "s2.jsonl")
        other.metadata = {"cwd": str(tmp_path / "other")}
        other.source_path.write_text("contains refactor", encoding="utf-8")

        spec = make_query_spec(keyword="refactor", project_path=tmp_path / "repo")
        result = filter_sessions_by_query(agent, [session, other], spec)
        assert [item.id for item in result] == ["s1"]

    def test_provider_scope_excludes_other_agents(self, tmp_path):
        agent = DummyAgent(name="kimi")
        session = make_session("s1", "refactor", tmp_path / "s1.jsonl")
        spec = make_query_spec(agent_names={"codex"})

        assert filter_sessions_by_query(agent, [session], spec) == []

    def test_role_scope_matches_keyword_only_inside_matching_roles(self, tmp_path):
        session = make_session("s1", "fatal in title", tmp_path / "s1.jsonl")
        session.source_path.write_text("fatal in file", encoding="utf-8")
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {
                    "messages": [
                        {"role": "user", "parts": [{"type": "text", "text": "contains fatal"}]},
                        {"role": "assistant", "parts": [{"type": "text", "text": "no hit"}]},
                    ]
                }
            },
        )

        result = filter_sessions_by_query(
            agent,
            [session],
            make_query_spec(keyword="fatal", roles={"assistant"}),
        )

        assert result == []

    def test_role_scope_matches_existing_role_without_keyword(self, tmp_path):
        session = make_session("s1", "session", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {
                    "messages": [
                        {"role": "tool", "parts": [{"type": "text", "text": "ran tool"}]},
                    ]
                }
            },
        )

        result = filter_sessions_by_query(
            agent,
            [session],
            make_query_spec(roles={"tool"}),
        )

        assert result == [session]


class TestSearchSessionsByQuery:
    def test_indexed_search_preserves_snippet_and_rank(self, tmp_path):
        agent = DummyAgent(name="codex")
        session = make_session("s1", "Auth timeout", tmp_path / "s1.jsonl")
        index = mock.MagicMock()
        index.is_available = True
        index.search.return_value = [
            SearchResult(
                agent_name="codex",
                session_id="s1",
                title="Auth timeout",
                snippet="...**auth** timeout during login...",
                rank=3.25,
            )
        ]

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            result = search_sessions_by_query(agent, [session], make_query_spec(keyword="auth timeout"))

        assert result == [
            SearchSessionMatch(
                agent=agent,
                session=session,
                snippet="...**auth** timeout during login...",
                rank=3.25,
            )
        ]
        index.update.assert_called_once_with(agent, [session])
        index.search.assert_called_once_with("auth timeout", agent_names={"codex"})

    def test_indexed_search_filters_to_scoped_sessions_without_truncating_index_update(self, tmp_path):
        agent = DummyAgent(name="codex")
        scoped = make_session("s1", "Scoped", tmp_path / "s1.jsonl")
        scoped.metadata = {"cwd": str(tmp_path / "repo")}
        outside = make_session("s2", "Outside", tmp_path / "s2.jsonl")
        outside.metadata = {"cwd": str(tmp_path / "other")}
        index = mock.MagicMock()
        index.is_available = True
        index.search.return_value = [
            SearchResult(agent_name="codex", session_id="s1", title="Scoped", snippet="**bug**", rank=1.0),
            SearchResult(agent_name="codex", session_id="s2", title="Outside", snippet="**bug**", rank=2.0),
        ]

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            result = search_sessions_by_query(
                agent,
                [scoped, outside],
                make_query_spec(keyword="bug", project_path=tmp_path / "repo"),
            )

        assert [match.session.id for match in result] == ["s1"]
        index.update.assert_called_once_with(agent, [scoped, outside])

    def test_fallback_search_builds_english_snippet_when_fts_unavailable(self, tmp_path):
        session = make_session("s1", "Auth session", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {
                    "messages": [
                        {"role": "user", "parts": [{"type": "text", "text": "login failed after auth timeout"}]},
                    ]
                }
            },
        )
        index = mock.MagicMock()
        index.is_available = False

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            result = search_sessions_by_query(agent, [session], make_query_spec(keyword="auth timeout"))

        assert len(result) == 1
        assert result[0].snippet == "login failed after **auth timeout**"
        assert result[0].rank == 0.0

    def test_fallback_search_builds_cjk_snippet_when_fts_unavailable(self, tmp_path):
        session = make_session("s1", "无关标题", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {
                    "messages": [
                        {"role": "user", "parts": [{"type": "text", "text": "修复认证模块的问题"}]},
                    ]
                }
            },
        )
        index = mock.MagicMock()
        index.is_available = False

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            result = search_sessions_by_query(agent, [session], make_query_spec(keyword="认证"))

        assert len(result) == 1
        assert result[0].snippet == "修复**认证**模块的问题"
        assert result[0].rank == 0.0


class TestLimitQueryMatches:
    def test_limit_matches_applies_global_sort(self, tmp_path):
        agent_a = DummyAgent(name="codex")
        agent_b = DummyAgent(name="kimi")
        session_a = make_session("s1", "a", tmp_path / "a.jsonl")
        session_a.updated_at = datetime(2026, 1, 1, 10, 0, 0)
        session_b = make_session("s2", "b", tmp_path / "b.jsonl")
        session_b.updated_at = datetime(2026, 1, 1, 11, 0, 0)

        result = limit_query_matches([(agent_a, session_a), (agent_b, session_b)], 1)

        assert [(agent.name, session.id) for agent, session in result] == [("kimi", "s2")]


class TestLimitSearchMatches:
    def test_limit_search_matches_sorts_by_rank_time_and_provider(self, tmp_path):
        codex = DummyAgent(name="codex")
        kimi = DummyAgent(name="kimi")
        older_high_rank = make_session("s1", "high", tmp_path / "s1.jsonl")
        older_high_rank.updated_at = datetime(2026, 1, 1, 10, 0, 0)
        newer_low_rank = make_session("s2", "low", tmp_path / "s2.jsonl")
        newer_low_rank.updated_at = datetime(2026, 1, 1, 12, 0, 0)
        tie_newer = make_session("s3", "tie newer", tmp_path / "s3.jsonl")
        tie_newer.updated_at = datetime(2026, 1, 1, 11, 0, 0)
        tie_older = make_session("s4", "tie older", tmp_path / "s4.jsonl")
        tie_older.updated_at = datetime(2026, 1, 1, 9, 0, 0)

        result = limit_search_matches(
            [
                SearchSessionMatch(agent=kimi, session=newer_low_rank, snippet="low", rank=0.5),
                SearchSessionMatch(agent=codex, session=tie_older, snippet="tie", rank=1.0),
                SearchSessionMatch(agent=kimi, session=tie_newer, snippet="tie", rank=1.0),
                SearchSessionMatch(agent=codex, session=older_high_rank, snippet="high", rank=2.0),
            ],
            limit=3,
        )

        assert [(match.agent.name, match.session.id) for match in result] == [
            ("codex", "s1"),
            ("kimi", "s3"),
            ("codex", "s4"),
        ]


class TestExtractSessionProjectPath:
    def test_prefers_cwd_then_directory(self, tmp_path):
        session = make_session("s1", "session", tmp_path / "s1.jsonl")
        session.metadata = {"cwd": str(tmp_path / "repo"), "directory": str(tmp_path / "ignored")}

        assert extract_session_project_path(session) == (tmp_path / "repo").resolve()

    def test_uses_directory_when_cwd_missing(self, tmp_path):
        session = make_session("s1", "session", tmp_path / "s1.jsonl")
        session.metadata = {"directory": str(tmp_path / "repo")}

        assert extract_session_project_path(session) == (tmp_path / "repo").resolve()
