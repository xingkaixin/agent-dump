"""
测试 query_filter.py 模块
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from unittest import mock

from locale_helpers import Keys, expect
import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.agents.zcode import ZCodeAgent
from agent_dump.query_filter import (
    QuerySpec,
    SearchSessionMatch,
    extract_session_working_directory,
    filter_sessions,
    filter_sessions_by_query,
    limit_query_session_matches,
    limit_search_matches,
    parse_query,
    parse_query_uri,
    query_session_matches,
    search_sessions_by_query,
)
from agent_dump.query_semantics import TextQuery, TextQueryMode
from agent_dump.search_index import SearchIndex, SearchResult


class DummyAgent(BaseAgent):
    """用于测试的简化 Agent"""

    def __init__(self, name: str = "codex", session_data: dict[str, dict] | None = None):
        super().__init__(name=name, display_name="Dummy")
        self._session_data = session_data or {}

    def scan(self) -> list[Session]:
        return []

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        return []

    def export_session(self, session: Session, output_dir: Path) -> Path:
        raise NotImplementedError

    def get_session_data(self, session: Session) -> dict:
        return self._session_data.get(session.id, {})


class CountingAgent(DummyAgent):
    def __init__(self, name: str = "codex", session_data: dict[str, dict] | None = None):
        super().__init__(name=name, session_data=session_data)
        self.data_reads = 0

    def get_session_data(self, session: Session) -> dict:
        self.data_reads += 1
        return super().get_session_data(session)


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
        agent_names=frozenset(agent_names) if agent_names is not None else None,
        keyword=keyword,
        project_path=project_path,
        roles=frozenset(roles) if roles is not None else None,
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
        assert isinstance(result.agent_names, frozenset)

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

    def test_parse_limit_larger_than_sqlite_integer_raises(self):
        with pytest.raises(ValueError) as exc_info:
            parse_query(
                "role:user limit:9223372036854775808 bug",
                {"opencode", "codex", "kimi", "claudecode"},
            )

        assert str(exc_info.value) == expect(Keys.QUERY_ERROR_LIMIT_TOO_LARGE)


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

    @pytest.mark.parametrize("agent_cls", (OpenCodeAgent, ZCodeAgent))
    def test_index_precedes_sqlite_provider_full_scan(self, agent_cls, tmp_path):
        agent = agent_cls()
        session = make_session("s1", "title", tmp_path / "provider.db")

        with (
            mock.patch("agent_dump.query_filter._try_indexed_search", return_value=[session]) as indexed_search,
            mock.patch.object(agent, "filter_sessions_by_keyword", return_value=[session]) as provider_search,
        ):
            result = filter_sessions(agent, [session], "keyword")

        assert result == [session]
        indexed_search.assert_called_once()
        provider_search.assert_not_called()

    def test_provider_fast_path_remains_the_index_fallback(self, tmp_path):
        agent = DummyAgent(name="opencode")
        session = make_session("s1", "title", tmp_path / "provider.db")

        with (
            mock.patch("agent_dump.query_filter._try_indexed_search", return_value=None),
            mock.patch.object(agent, "filter_sessions_by_keyword", return_value=[session]) as provider_search,
        ):
            result = filter_sessions(agent, [session], "keyword")

        assert result == [session]
        provider_search.assert_called_once_with([session], "keyword")

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

        assert result == [session]
        mock_get_session_data.assert_called_once_with(session)

    def test_filter_matches_logical_text_when_json_source_uses_unicode_escapes(self, tmp_path):
        source_path = tmp_path / "s1.jsonl"
        source_path.write_text(json.dumps({"text": "认证"}, ensure_ascii=True), encoding="utf-8")
        session = make_session("s1", "普通标题", source_path)
        agent = DummyAgent(
            name="codex",
            session_data={"s1": {"messages": [{"parts": [{"type": "text", "text": "认证"}]}]}},
        )

        with mock.patch("agent_dump.query_filter._try_indexed_search", return_value=None):
            result = filter_sessions(agent, [session], "认证")

        assert result == [session]

    def test_query_keyword_is_a_literal_phrase(self, tmp_path):
        session = make_session("s1", "普通标题", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={"s1": {"messages": [{"parts": [{"type": "text", "text": "auth failed before timeout"}]}]}},
        )

        with mock.patch("agent_dump.query_filter._try_indexed_search", return_value=None):
            result = filter_sessions(agent, [session], "auth timeout")

        assert result == []

    def test_filter_directory_session_searches_every_jsonl(self, tmp_path):
        """目录型会话（Kimi）的兜底提取会读目录下所有 *.jsonl。

        本测试原名 `..._prefers_wire_file` 并断言 "other-hit" 匹配不到，但那只是因为
        AD-133 之前带连字符的关键词会让 FTS5 报 `no such column: hit` 并被静默吞掉。
        _fallback_extract_from_source（search_index.py:188）对目录是 glob("*.jsonl")，
        从来没有偏好 wire.jsonl 的逻辑。
        """
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        (session_dir / "wire.jsonl").write_text("wire-hit", encoding="utf-8")
        (session_dir / "other.jsonl").write_text("other-hit", encoding="utf-8")
        session = make_session("s1", "普通标题", session_dir)
        agent = DummyAgent(name="kimi")

        assert filter_sessions(agent, [session], "wire-hit") == [session]
        assert filter_sessions(agent, [session], "other-hit") == [session]
        assert filter_sessions(agent, [session], "absent-token") == []

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

    @pytest.mark.parametrize(
        ("agent_cls", "db_name"),
        (
            (OpenCodeAgent, "opencode.db"),
            (ZCodeAgent, "db.sqlite"),
        ),
    )
    def test_filter_sqlite_provider_matches_standardized_part_text(self, agent_cls, db_name, tmp_path):
        db_path = tmp_path / db_name
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
            ("m1", "s1", 1, json.dumps({"role": "user", "content": "provider-private-token"})),
        )
        cursor.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            ("p1", "m1", 1, json.dumps({"type": "text", "text": "Fatal issue 关键字命中"})),
        )
        conn.commit()
        conn.close()

        agent = agent_cls()
        agent.db_path = db_path
        sessions = [
            make_session("s1", "Normal title", db_path),
            make_session("s2", "Another title", db_path),
        ]

        result = filter_sessions(agent, sessions, "fatal")
        assert [s.id for s in result] == ["s1"]
        assert [s.id for s in filter_sessions(agent, sessions, "关键字")] == ["s1"]
        assert filter_sessions(agent, sessions, "provider-private-token") == []

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

    def test_path_scope_does_not_treat_provider_project_or_source_as_working_directory(self, tmp_path):
        agent = DummyAgent(name="claudecode")
        repo_root = tmp_path / "repo"
        source = repo_root / "provider-project" / "s1.jsonl"
        session = make_session("s1", "provider project only", source)
        session.metadata = {"project": str(repo_root)}
        spec = make_query_spec(project_path=repo_root)

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
    @pytest.mark.parametrize(
        ("keyword", "expected_ids"),
        (
            ("auth timeout", {"cross-fields"}),
            (" auth   timeout auth ", {"cross-fields"}),
            ("认证", {"cjk-adjacent"}),
            ('AND NEAR * "quoted"', {"operators"}),
        ),
    )
    def test_index_and_in_process_adapters_select_the_same_sessions(self, keyword, expected_ids, tmp_path):
        sessions = [
            make_session("cross-fields", "Auth incident", tmp_path / "cross-fields.jsonl"),
            make_session("cjk-adjacent", "CJK exact", tmp_path / "cjk-adjacent.jsonl"),
            make_session("cjk-separated", "CJK separated", tmp_path / "cjk-separated.jsonl"),
            make_session("operators", "Operators", tmp_path / "operators.jsonl"),
        ]
        for session in sessions:
            session.source_path.write_text("{}", encoding="utf-8")
        agent = DummyAgent(
            name="codex",
            session_data={
                "cross-fields": {
                    "messages": [{"role": "user", "parts": [{"type": "text", "text": "request timeout"}]}]
                },
                "cjk-adjacent": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "修复认证模块"}]}]},
                "cjk-separated": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "认知经过证明"}]}]},
                "operators": {
                    "messages": [{"role": "user", "parts": [{"type": "text", "text": 'literal AND NEAR * "quoted"'}]}]
                },
            },
        )
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, sessions)
        spec = make_query_spec(keyword=keyword)

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            indexed = search_sessions_by_query(agent, sessions, spec)
        unavailable = mock.MagicMock()
        unavailable.is_available = False
        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=unavailable):
            fallback = search_sessions_by_query(agent, sessions, spec)

        indexed_ids = {match.session.id for match in indexed}
        fallback_ids = {match.session.id for match in fallback}
        assert indexed_ids == fallback_ids == expected_ids

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
        index.search.assert_called_once_with(
            TextQuery.parse("auth timeout", TextQueryMode.SEARCH_TERMS),
            agent_names={"codex"},
            session_keys={("codex", "s1")},
            limit=None,
        )

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
        assert result[0].snippet == "login failed after **auth** timeout"
        assert result[0].rank == 0.0

    def test_fallback_search_matches_terms_across_title_and_transcript(self, tmp_path):
        session = make_session("s1", "Auth incident", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "request timeout"}]}]}
            },
        )
        index = mock.MagicMock()
        index.is_available = False

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            result = search_sessions_by_query(agent, [session], make_query_spec(keyword="auth timeout"))

        assert [match.session.id for match in result] == ["s1"]
        assert "auth" in result[0].snippet.lower()

    def test_fallback_search_rejects_non_adjacent_cjk(self, tmp_path):
        session = make_session("s1", "无关标题", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={"s1": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "认知经过证明"}]}]}},
        )
        index = mock.MagicMock()
        index.is_available = False

        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            result = search_sessions_by_query(agent, [session], make_query_spec(keyword="认证"))

        assert result == []

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

    def test_role_search_snippet_only_uses_allowed_message_evidence(self, tmp_path):
        session = make_session("s1", "session", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {
                    "messages": [
                        {"role": "user", "parts": [{"type": "text", "text": "fatal user evidence"}]},
                        {
                            "role": "assistant",
                            "parts": [{"type": "text", "text": "fatal assistant evidence"}],
                        },
                    ]
                }
            },
        )

        with mock.patch("agent_dump.query_filter.SearchIndex") as index_factory:
            result = search_sessions_by_query(
                agent,
                [session],
                make_query_spec(keyword="fatal", roles={"assistant"}),
            )

        assert result == [
            SearchSessionMatch(
                agent=agent,
                session=session,
                snippet="**fatal** assistant evidence",
                rank=0.0,
                matched_role="assistant",
            )
        ]
        index_factory.assert_not_called()

    def test_role_query_without_keyword_preserves_role_evidence(self, tmp_path):
        session = make_session("s1", "session", tmp_path / "s1.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={
                "s1": {
                    "messages": [
                        {"role": "tool", "parts": [{"type": "text", "text": "ran tests"}]},
                    ]
                }
            },
        )

        result = query_session_matches(agent, [session], make_query_spec(roles={"tool"}))

        assert result[0].session is session
        assert result[0].matched_role == "tool"
        assert result[0].snippet == "ran tests"

    def test_role_query_reports_unreadable_session_and_preserves_other_matches(self, tmp_path, capsys):
        broken = make_session("broken", "broken", tmp_path / "broken.jsonl")
        healthy = make_session("healthy", "healthy", tmp_path / "healthy.jsonl")
        agent = DummyAgent(
            name="codex",
            session_data={
                "healthy": {
                    "messages": [
                        {"role": "user", "parts": [{"type": "text", "text": "matching evidence"}]},
                    ]
                }
            },
        )
        original_get_session_data = agent.get_session_data

        def get_session_data(session: Session) -> dict:
            if session is broken:
                raise OSError("source disappeared")
            return original_get_session_data(session)

        with mock.patch.object(agent, "get_session_data", side_effect=get_session_data):
            result = query_session_matches(
                agent,
                [broken, healthy],
                make_query_spec(keyword="matching", roles={"user"}),
            )

        assert [match.session for match in result] == [healthy]
        assert (
            expect(
                Keys.WARN_SESSION_READ_SKIPPED,
                uri="codex://broken",
                error="source disappeared",
            )
            in capsys.readouterr().err
        )


class TestRoleLimitPushdown:
    @staticmethod
    def _session(
        tmp_path: Path, session_id: str, updated_at: datetime, *, created_at: datetime | None = None
    ) -> Session:
        session = make_session(session_id, session_id, tmp_path / f"{session_id}.jsonl")
        session.updated_at = updated_at
        session.created_at = created_at or updated_at
        return session

    @staticmethod
    def _data(sessions: list[Session], *, text: str = "matching evidence") -> dict[str, dict]:
        return {
            session.id: {"messages": [{"role": "user", "parts": [{"type": "text", "text": text}]}]}
            for session in sessions
        }

    def test_high_hit_limit_reads_only_the_best_session(self, tmp_path) -> None:
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        sessions = [self._session(tmp_path, f"s-{index:02d}", now - timedelta(minutes=index)) for index in range(30)]
        sessions.reverse()
        agent = CountingAgent(session_data=self._data(sessions))

        result = query_session_matches(
            agent,
            sessions,
            make_query_spec(keyword="matching", roles={"user"}, limit=1),
        )

        assert [match.session.id for match in result] == ["s-00"]
        assert agent.data_reads == 1

    def test_scan_stops_only_after_enough_actual_matches(self, tmp_path) -> None:
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        sessions = [self._session(tmp_path, f"s-{index:02d}", now - timedelta(minutes=index)) for index in range(10)]
        data = self._data(sessions)
        for session in sessions[:5]:
            data[session.id] = {"messages": [{"role": "user", "parts": [{"type": "text", "text": "not relevant"}]}]}
        agent = CountingAgent(session_data=data)

        result = query_session_matches(
            agent,
            list(reversed(sessions)),
            make_query_spec(keyword="matching", roles={"user"}, limit=1),
        )

        assert [match.session.id for match in result] == ["s-05"]
        assert agent.data_reads == 6

    def test_no_match_still_reads_every_scoped_session(self, tmp_path) -> None:
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        sessions = [self._session(tmp_path, f"s-{index:02d}", now - timedelta(minutes=index)) for index in range(10)]
        agent = CountingAgent(session_data=self._data(sessions, text="not relevant"))

        result = query_session_matches(
            agent,
            sessions,
            make_query_spec(keyword="matching", roles={"user"}, limit=1),
        )

        assert result == []
        assert agent.data_reads == len(sessions)

    def test_no_limit_preserves_full_input_order(self, tmp_path) -> None:
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        newer = self._session(tmp_path, "newer", now)
        older = self._session(tmp_path, "older", now - timedelta(hours=1))
        sessions = [older, newer]
        agent = CountingAgent(session_data=self._data(sessions))

        result = query_session_matches(
            agent,
            sessions,
            make_query_spec(keyword="matching", roles={"user"}),
        )

        assert [match.session.id for match in result] == ["older", "newer"]
        assert agent.data_reads == 2

    def test_path_scope_is_applied_before_role_limit(self, tmp_path) -> None:
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        outside = self._session(tmp_path, "outside", now)
        outside.metadata = {"cwd": str(tmp_path / "outside")}
        inside = self._session(tmp_path, "inside", now - timedelta(hours=1))
        inside.metadata = {"cwd": str(tmp_path / "repo")}
        sessions = [outside, inside]
        agent = CountingAgent(session_data=self._data(sessions))

        result = query_session_matches(
            agent,
            sessions,
            make_query_spec(
                keyword="matching",
                project_path=tmp_path / "repo",
                roles={"user"},
                limit=1,
            ),
        )

        assert [match.session.id for match in result] == ["inside"]
        assert agent.data_reads == 1

    def test_sort_key_normalizes_timezones_and_uses_created_at_then_id(self, tmp_path) -> None:
        updated = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
        created = datetime(2026, 8, 10, 11, tzinfo=timezone.utc)
        id_later = self._session(tmp_path, "b", updated.replace(tzinfo=None), created_at=created.replace(tzinfo=None))
        id_first = self._session(tmp_path, "a", updated, created_at=created)
        created_first = self._session(tmp_path, "z", updated, created_at=created + timedelta(minutes=1))
        sessions = [id_later, id_first, created_first]
        agent = CountingAgent(session_data=self._data(sessions))

        first = query_session_matches(agent, sessions, make_query_spec(roles={"user"}, limit=1))
        second_agent = CountingAgent(session_data=self._data(sessions[:2]))
        second = query_session_matches(second_agent, sessions[:2], make_query_spec(roles={"user"}, limit=1))

        assert [match.session.id for match in first] == ["z"]
        assert [match.session.id for match in second] == ["a"]

    def test_per_provider_top_limit_matches_full_scan_oracle(self, tmp_path) -> None:
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        codex_sessions = [
            self._session(tmp_path, "c-old", now - timedelta(hours=4)),
            self._session(tmp_path, "c-new", now),
            self._session(tmp_path, "c-mid", now - timedelta(hours=2)),
        ]
        kimi_sessions = [
            self._session(tmp_path, "k-old", now - timedelta(hours=5)),
            self._session(tmp_path, "k-new", now - timedelta(hours=1)),
            self._session(tmp_path, "k-mid", now - timedelta(hours=3)),
        ]
        optimized_agents = [
            CountingAgent(name="codex", session_data=self._data(codex_sessions)),
            CountingAgent(name="kimi", session_data=self._data(kimi_sessions)),
        ]
        full_agents = [
            CountingAgent(name="codex", session_data=self._data(codex_sessions)),
            CountingAgent(name="kimi", session_data=self._data(kimi_sessions)),
        ]
        session_groups = [codex_sessions, kimi_sessions]

        optimized = limit_query_session_matches(
            [
                match
                for agent, sessions in zip(optimized_agents, session_groups, strict=True)
                for match in query_session_matches(
                    agent,
                    sessions,
                    make_query_spec(keyword="matching", roles={"user"}, limit=2),
                )
            ],
            2,
        )
        oracle = limit_query_session_matches(
            [
                match
                for agent, sessions in zip(full_agents, session_groups, strict=True)
                for match in query_session_matches(
                    agent,
                    sessions,
                    make_query_spec(keyword="matching", roles={"user"}),
                )
            ],
            2,
        )

        def project(matches: list[SearchSessionMatch]) -> list[tuple[str, str, str, float, str | None]]:
            return [
                (match.agent.name, match.session.id, match.snippet, match.rank, match.matched_role) for match in matches
            ]

        assert project(optimized) == project(oracle)
        assert [agent.data_reads for agent in optimized_agents] == [2, 2]
        assert [agent.data_reads for agent in full_agents] == [3, 3]


class TestLimitQueryMatches:
    def test_limit_query_session_matches_preserves_selected_evidence(self, tmp_path):
        agent = DummyAgent(name="codex")
        older = make_session("s-old", "old", tmp_path / "old.jsonl")
        older.updated_at = datetime(2026, 1, 1, 10, 0, 0)
        newer = make_session("s-new", "new", tmp_path / "new.jsonl")
        newer.updated_at = datetime(2026, 1, 1, 11, 0, 0)
        matches = [
            SearchSessionMatch(agent, older, "**bug** old", 0.0, "user"),
            SearchSessionMatch(agent, newer, "**bug** new", 0.0, "assistant"),
        ]

        result = limit_query_session_matches(matches, 1)

        assert result == [matches[1]]

    def test_limit_sorts_even_when_it_does_not_truncate(self, tmp_path) -> None:
        agent = DummyAgent(name="codex")
        older = make_session("s-old", "old", tmp_path / "old.jsonl")
        older.updated_at = datetime(2026, 1, 1, 10, 0, 0)
        newer = make_session("s-new", "new", tmp_path / "new.jsonl")
        newer.updated_at = datetime(2026, 1, 1, 11, 0, 0)
        matches = [
            SearchSessionMatch(agent, older, "old", 0.0, "user"),
            SearchSessionMatch(agent, newer, "new", 0.0, "user"),
        ]

        result = limit_query_session_matches(matches, 5)

        assert result == [matches[1], matches[0]]


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

        assert extract_session_working_directory(session) == (tmp_path / "repo").resolve()

    def test_uses_directory_when_cwd_missing(self, tmp_path):
        session = make_session("s1", "session", tmp_path / "s1.jsonl")
        session.metadata = {"directory": str(tmp_path / "repo")}

        assert extract_session_working_directory(session) == (tmp_path / "repo").resolve()


class TestSearchLimitPushdownSafety:
    """AD-154：只有在没有后置过滤时才允许把 limit 交给索引。"""

    @staticmethod
    def _run(spec, *, project_path=None):
        agent = DummyAgent()
        now = datetime.now(timezone.utc)
        session = Session(
            id="s1",
            title="T",
            created_at=now,
            updated_at=now,
            source_path=Path("/tmp/s1.jsonl"),
            metadata={"cwd": "/work/project"},
        )
        index = mock.MagicMock()
        index.is_available = True
        index.search.return_value = []
        with mock.patch("agent_dump.query_filter.SearchIndex", return_value=index):
            search_sessions_by_query(agent, [session], spec)
        return index

    def test_plain_keyword_search_pushes_the_limit_down(self):
        index = self._run(make_query_spec(keyword="alpha", limit=10))

        assert index.search.call_args.kwargs["limit"] == 10

    def test_project_scope_keeps_the_full_result_set(self):
        """scope 过滤发生在拿到结果之后；先裁剪会把本该入选的会话挡在 top-L 之外。"""
        index = self._run(make_query_spec(keyword="alpha", limit=10, project_path=Path("/work/project")))

        assert index.search.call_args.kwargs["limit"] is None

    def test_no_limit_stays_unlimited(self):
        index = self._run(make_query_spec(keyword="alpha"))

        assert index.search.call_args.kwargs["limit"] is None
