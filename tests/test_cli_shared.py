"""
测试 CLI 共享辅助模块
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from unittest import mock

from locale_helpers import ALL_LANGUAGES, Keys, expect
import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import (
    build_no_agents_found_diagnostic,
    collect_query_matches,
    collect_search_matches,
    display_search_results,
    display_sessions_list,
    export_sessions_for_formats,
    group_sessions_by_time,
    render_agent_search_roots,
    render_query_summary,
    show_loading,
)
from agent_dump.exporting import ExportRunStatus
from agent_dump.paths import SearchRoot
from agent_dump.query_filter import QuerySpec, SearchSessionMatch
from agent_dump.rendering import format_session_metadata_summary, render_session_head, render_session_text
from agent_dump.scanner import AgentScanner
from agent_dump.text_safety import has_unsafe_body_characters
from agent_dump.uri_support import find_session_by_id, parse_uri


def make_session(
    session_id: str,
    title: str,
    *,
    created_at: datetime | None = None,
    source_path: Path | None = None,
    metadata: dict | None = None,
) -> Session:
    session_time = created_at or datetime(2026, 1, 1, 12, 0, 0)
    return Session(
        id=session_id,
        title=title,
        created_at=session_time,
        updated_at=session_time,
        source_path=source_path or Path(f"/tmp/{session_id}.jsonl"),
        metadata=metadata or {},
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


class SearchRootAgent(BaseAgent):
    def __init__(self, roots: tuple[SearchRoot, ...]) -> None:
        super().__init__("typed", "Typed Agent")
        self._roots = roots

    def is_available(self) -> bool:
        return False

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        del days
        return []

    def get_session_data(self, session: Session) -> dict[str, Any]:
        del session
        return {}

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        return self._roots


def test_diagnostic_search_roots_use_the_base_agent_contract(tmp_path: Path) -> None:
    agent = SearchRootAgent((SearchRoot("typed root", tmp_path / "sessions"),))

    rendered = render_agent_search_roots((agent,))
    diagnostic = build_no_agents_found_diagnostic(AgentScanner((agent,)))

    assert rendered == (f"Typed Agent: typed root: {tmp_path / 'sessions'}",)
    assert diagnostic.searched_roots == rendered


class TestParseUri:
    """测试 parse_uri 函数"""

    def test_parse_uri_codex_standard(self):
        """测试 Codex 标准 URI 解析"""
        assert parse_uri("codex://019c8d87-ecc4-7080-bde9-3e257c97cb99") == (
            "codex",
            "019c8d87-ecc4-7080-bde9-3e257c97cb99",
        )

    def test_parse_uri_codex_threads_variant(self):
        """测试 Codex threads 变体 URI 解析"""
        assert parse_uri("codex://threads/019c8d87-ecc4-7080-bde9-3e257c97cb99") == (
            "codex",
            "019c8d87-ecc4-7080-bde9-3e257c97cb99",
        )

    def test_parse_uri_codex_threads_empty_session_id(self):
        """测试 Codex threads 变体缺少 session_id 时返回 None"""
        assert parse_uri("codex://threads/") is None

    def test_parse_uri_invalid_format(self):
        """测试非 URI 字符串返回 None"""
        assert parse_uri("invalid-uri") is None

    def test_parse_uri_unsupported_scheme(self):
        """测试不支持的 URI scheme 返回 None"""
        assert parse_uri("unknown://session-001") is None

    def test_parse_uri_cursor(self):
        """测试 Cursor URI 解析"""
        assert parse_uri("cursor://request-001") == ("cursor", "request-001")

    def test_parse_uri_zcode(self):
        """测试 ZCode URI 解析"""
        assert parse_uri("zcode://sess-001") == ("zcode", "sess-001")


class TestQueryHelpers:
    def test_render_query_summary_includes_structured_fields(self, tmp_path):
        summary = render_query_summary(
            make_query_spec(
                agent_names={"codex", "kimi"},
                keyword="bug",
                project_path=tmp_path,
                roles={"user"},
                limit=5,
            )
        )

        assert f"路径={tmp_path}" in summary
        assert "关键词=bug" in summary
        assert "providers=codex,kimi" in summary
        assert "roles=user" in summary
        assert "limit=5" in summary

    def test_collect_query_matches_applies_global_limit(self):
        older = make_session("s-old", "old", created_at=datetime(2026, 1, 1, 10, 0, 0))
        newer = make_session("s-new", "new", created_at=datetime(2026, 1, 1, 11, 0, 0))

        agent_a = mock.MagicMock()
        agent_a.name = "codex"
        agent_a.get_sessions.return_value = [older]

        agent_b = mock.MagicMock()
        agent_b.name = "kimi"
        agent_b.get_sessions.return_value = [newer]

        match_b = SearchSessionMatch(agent=agent_b, session=newer, snippet="new", rank=0.0)
        with mock.patch("agent_dump.cli_shared.query_session_groups", return_value=[match_b]):
            matched = collect_query_matches(
                [(agent_a, [older]), (agent_b, [newer])],
                spec=make_query_spec(keyword="bug", limit=1),
            )

        assert {name: [session.id for session in sessions] for name, sessions in matched.items()} == {"kimi": ["s-new"]}

    def test_collect_search_matches_applies_global_rank_sort_and_limit(self):
        older = make_session("s-old", "old", created_at=datetime(2026, 1, 1, 10, 0, 0))
        newer = make_session("s-new", "new", created_at=datetime(2026, 1, 1, 11, 0, 0))

        agent_a = mock.MagicMock()
        agent_a.name = "codex"
        agent_a.get_sessions.return_value = [older]

        agent_b = mock.MagicMock()
        agent_b.name = "kimi"
        agent_b.get_sessions.return_value = [newer]

        match_b = SearchSessionMatch(agent=agent_b, session=newer, snippet="new", rank=2.0)

        with mock.patch("agent_dump.cli_shared.search_session_groups", return_value=[match_b]):
            result = collect_search_matches(
                [(agent_a, [older]), (agent_b, [newer])],
                spec=make_query_spec(keyword="bug", limit=1),
            )

        assert [(match.agent.name, match.session.id) for match in result] == [("kimi", "s-new")]

    def test_display_search_results_shows_snippet_uri_updated_provider_and_rank(self, capsys):
        session = make_session("s1", "Auth Timeout", created_at=datetime(2026, 1, 1, 10, 0, 0))
        agent = mock.MagicMock()
        agent.display_name = "Codex"
        agent.get_formatted_title.return_value = "Auth Timeout (2026-01-01 10:00)"
        agent.get_session_uri.return_value = "codex://s1"
        match = SearchSessionMatch(
            agent=agent,
            session=session,
            snippet="login failed after **auth timeout**",
            rank=2.5,
        )

        display_search_results([match])

        output = capsys.readouterr().out
        assert "Codex" in output
        assert "codex://s1" in output
        assert "2026-01-01" in output
        assert "2.5" in output
        assert "login failed after **auth timeout**" in output

    def test_display_search_results_sanitizes_every_provider_owned_field(self, capsys):
        poison = "value\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        session = make_session(poison, poison)
        agent = mock.MagicMock()
        agent.display_name = poison
        agent.get_formatted_title.return_value = poison
        agent.get_session_uri.return_value = poison

        display_search_results([SearchSessionMatch(agent=agent, session=session, snippet=poison, rank=1.0)])

        output = capsys.readouterr().out
        assert not has_unsafe_body_characters(output)
        assert "FORGED" in output


class TestFindSessionById:
    """测试 find_session_by_id 函数"""

    def test_find_session_by_id_found(self):
        """测试跨 agent 查找命中会话"""
        scanner = mock.MagicMock()
        target_session = mock.MagicMock(id="target")
        agent2 = mock.MagicMock()
        scanner.find_session_by_id.return_value = (agent2, target_session)

        result = find_session_by_id(scanner, "target")

        assert result == (agent2, target_session)
        scanner.find_session_by_id.assert_called_once_with("target", agent_name=None)

    def test_find_session_by_id_not_found(self):
        """测试找不到会话时返回 None"""
        scanner = mock.MagicMock()
        scanner.find_session_by_id.return_value = None

        result = find_session_by_id(scanner, "missing")

        assert result is None
        scanner.find_session_by_id.assert_called_once_with("missing", agent_name=None)

    def test_find_session_by_id_limits_to_agent_name(self):
        scanner = mock.MagicMock()
        opencode_agent = mock.MagicMock()
        target_session = mock.MagicMock(id="target")
        scanner.find_session_by_id.return_value = (opencode_agent, target_session)

        result = find_session_by_id(scanner, "target", agent_name="opencode")

        assert result == (opencode_agent, target_session)
        scanner.find_session_by_id.assert_called_once_with("target", agent_name="opencode")

    def test_find_session_by_id_preserves_scanner_failure_isolation(self):
        scanner = mock.MagicMock()
        target_session = mock.MagicMock(id="target")
        ok_agent = mock.MagicMock()
        scanner.find_session_by_id.return_value = (ok_agent, target_session)

        result = find_session_by_id(scanner, "target")

        assert result == (ok_agent, target_session)


class TestExportSessions:
    """测试 export_sessions 函数"""

    def test_export_single_session(self, tmp_path):
        """测试导出单个会话"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"

        mock_session = make_session("session-001", "Test Session")

        mock_agent.export_session.return_value = tmp_path / "test_agent" / "session-001.json"

        result = export_sessions_for_formats(mock_agent, [mock_session], ["json"], tmp_path)

        assert len(result) == 1
        mock_agent.export_session.assert_called_once_with(mock_session, tmp_path / "test_agent")

    def test_export_multiple_sessions(self, tmp_path):
        """测试导出多个会话"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"

        sessions = [
            make_session("session-001", "Session 1"),
            make_session("session-002", "Session 2"),
        ]

        mock_agent.export_session.side_effect = [
            tmp_path / "test_agent" / "session-001.json",
            tmp_path / "test_agent" / "session-002.json",
        ]

        result = export_sessions_for_formats(mock_agent, sessions, ["json"], tmp_path)

        assert len(result) == 2
        assert mock_agent.export_session.call_count == 2

    def test_export_with_error(self, tmp_path, capsys):
        """测试导出时出现错误的情况"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"

        sessions = [
            make_session("session-001", "Session 1"),
            make_session("session-002", "Session 2"),
        ]

        # 第一个成功，第二个失败
        mock_agent.export_session.side_effect = [
            tmp_path / "test_agent" / "session-001.json",
            Exception("Export failed"),
        ]

        result = export_sessions_for_formats(mock_agent, sessions, ["json"], tmp_path)

        assert len(result) == 1
        captured = capsys.readouterr()
        assert "错误" in captured.out or "Export failed" in captured.out

    def test_export_sanitizes_fields_and_emits_one_diagnostic_for_a_failure(self, tmp_path, capsys):
        poison = "value\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        agent = mock.MagicMock()
        agent.name = "test_agent"
        agent.display_name = poison
        agent.get_search_roots.return_value = ()
        agent.export_session.side_effect = RuntimeError(f"Export failed {poison}")

        export_sessions_for_formats(agent, [make_session("s1", poison)], ["json"], tmp_path)

        output = capsys.readouterr().out
        assert not has_unsafe_body_characters(output)
        assert output.count("Export failed") == 1
        assert output.count(expect(Keys.DIAGNOSTIC_HEADER)) == 1

    def test_export_all_failed_returns_structured_failure(self, tmp_path):
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"
        mock_agent.export_session.side_effect = RuntimeError("Export failed")

        result = export_sessions_for_formats(
            mock_agent,
            [make_session("session-001", "Session 1")],
            ["json"],
            tmp_path,
        )

        assert result.status is ExportRunStatus.FAILED
        assert result.exported_paths == ()

    def test_export_creates_directory(self, tmp_path):
        """测试导出时创建输出目录"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"

        mock_session = make_session("session-001", "Test Session")

        output_dir = tmp_path / "new_output"
        mock_agent.export_session.return_value = output_dir / "test_agent" / "session.json"

        export_sessions_for_formats(mock_agent, [mock_session], ["json"], output_dir)

        assert (output_dir / "test_agent").exists()

    def test_export_sessions_for_multiple_formats(self, tmp_path):
        """测试多格式导出会依次调用对应导出器"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"
        mock_agent.get_session_uri.return_value = "codex://session-001"
        mock_agent.get_session_data.return_value = {"messages": []}

        session = make_session("session-001", "Session 1")

        mock_agent.export_session.return_value = tmp_path / "test_agent" / "session-001.json"
        mock_agent.export_raw_session.return_value = tmp_path / "test_agent" / "session-001.raw.jsonl"

        result = export_sessions_for_formats(mock_agent, [session], ["json", "markdown", "raw"], tmp_path)

        assert len(result) == 3
        mock_agent.export_session.assert_called_once_with(session, tmp_path / "test_agent")
        mock_agent.export_raw_session.assert_called_once_with(session, tmp_path / "test_agent")

    def test_export_sessions_for_multiple_formats_supports_per_format_output_dirs(self, tmp_path):
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"
        mock_agent.get_session_uri.return_value = "codex://session-001"
        mock_agent.get_session_data.return_value = {"messages": []}

        session = make_session("session-001", "Session 1")
        json_root = tmp_path / "json-root"
        markdown_root = tmp_path / "markdown-root"
        raw_root = tmp_path / "raw-root"
        mock_agent.export_session.return_value = json_root / "test_agent" / "session-001.json"
        mock_agent.export_raw_session.return_value = raw_root / "test_agent" / "session-001.raw.jsonl"

        export_sessions_for_formats(
            mock_agent,
            [session],
            ["json", "markdown", "raw"],
            tmp_path,
            output_base_dirs={"json": json_root, "markdown": markdown_root, "raw": raw_root},
        )

        mock_agent.export_session.assert_called_once_with(session, json_root / "test_agent")
        mock_agent.export_raw_session.assert_called_once_with(session, raw_root / "test_agent")


def test_show_loading_sanitizes_non_tty_status(capsys):
    poison = "loading\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"

    with mock.patch("sys.stderr.isatty", return_value=False), show_loading(poison):
        pass

    output = capsys.readouterr().err
    assert not has_unsafe_body_characters(output)
    assert "FORGED" in output


class TestRenderSessionText:
    """测试 render_session_text 函数"""

    def test_render_session_text_skips_malformed_message_entries(self):
        session_data = {
            "messages": [
                "bare",
                None,
                {"role": "user", "parts": [{"type": "text", "text": "Hello"}]},
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "## 1. User" in output
        assert "Hello" in output

    def test_render_session_text_skips_developer_messages(self):
        """测试 URI 输出会过滤 developer 角色"""
        session_data = {
            "messages": [
                {
                    "role": "developer",
                    "parts": [{"type": "text", "text": "System instruction"}],
                },
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Hello"}],
                },
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "text": "Hi"}],
                },
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "Developer" not in output
        assert "System instruction" not in output
        assert "## 1. User" in output
        assert "## 2. Assistant" in output

    def test_render_session_text_sanitizes_uri_role_and_body_without_flattening_layout(self):
        poison = "value\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        output = render_session_text(
            f"codex://{poison}",
            {
                "messages": [
                    {
                        "role": poison,
                        "parts": [{"type": "text", "text": f"line one{poison}\nline two"}],
                    }
                ]
            },
        )

        assert not has_unsafe_body_characters(output)
        assert "line one" in output and "\nline two" in output
        assert output.count("\n") >= 5

    def test_render_session_text_skips_developer_like_user_context(self):
        """测试 URI 输出会过滤伪装成 user 的系统上下文"""
        session_data = {
            "messages": [
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "# AGENTS.md instructions for /path/project"}],
                },
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "<environment_context>\n  <cwd>/tmp</cwd>"}],
                },
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "真实用户问题"}],
                },
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "text": "真实助手回复"}],
                },
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "AGENTS.md instructions" not in output
        assert "<environment_context>" not in output
        assert "## 1. User" in output
        assert "真实用户问题" in output
        assert "## 2. Assistant" in output
        assert "真实助手回复" in output

    def test_render_session_text_skips_messages_without_text_parts(self):
        """测试无文本内容的消息会跳过"""
        session_data = {
            "messages": [
                {
                    "role": "assistant",
                    "parts": [{"type": "tool", "tool": "read_file"}],
                },
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "text": "有效文本"}],
                },
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "read_file" not in output
        assert "有效文本" in output
        assert "## 1. Assistant" in output

    def test_render_session_text_renders_subagent_tool_as_assistant_message(self):
        """测试 Codex subagent tool 会在 print 中渲染为 assistant 消息"""
        session_data = {
            "messages": [
                {
                    "role": "assistant",
                    "parts": [
                        {"type": "text", "text": "开始委托"},
                        {
                            "type": "tool",
                            "tool": "subagent",
                            "nickname": "Laplace",
                            "state": {"arguments": {"message": "检查 useConversation 边界"}},
                        },
                    ],
                }
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "## 1. Assistant" in output
        assert "开始委托" in output
        assert "## 2. Assistant (Laplace)" in output
        assert "检查 useConversation 边界" in output

    def test_render_session_text_renders_standalone_subagent_tool_message(self):
        """测试独立 tool 消息中的 subagent 调用也会按 assistant 展示"""
        session_data = {
            "messages": [
                {
                    "role": "tool",
                    "parts": [
                        {
                            "type": "tool",
                            "tool": "subagent",
                            "state": {
                                "prompt": "Read the files and summarize.",
                                "model": "composer-2-fast",
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "subagent_id": "subagent-001",
                    "parts": [{"type": "text", "text": "最终总结"}],
                },
            ]
        }

        output = render_session_text("cursor://abc", session_data)

        assert "## 1. Assistant" in output
        assert "Read the files and summarize." in output
        assert "## 2. Assistant" in output
        assert "最终总结" in output

    def test_render_session_text_renders_subagent_notification_with_nickname(self):
        """测试带 nickname 的 subagent 结果会显示对应 assistant 名字"""
        session_data = {
            "messages": [
                {
                    "role": "assistant",
                    "nickname": "Laplace",
                    "subagent_id": "agent-001",
                    "parts": [{"type": "text", "text": "最终结论"}],
                }
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "## 1. Assistant (Laplace)" in output
        assert "最终结论" in output

    def test_render_session_text_includes_plan_part_input(self):
        """测试 plan part 会按正文渲染"""
        session_data = {
            "messages": [
                {
                    "role": "assistant",
                    "parts": [
                        {
                            "type": "plan",
                            "input": "# 方案\n\n实现 plan 逻辑",
                            "output": None,
                            "approval_status": "success",
                        }
                    ],
                }
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "## 1. Assistant" in output
        assert "# 方案" in output
        assert "实现 plan 逻辑" in output

    def test_render_session_text_unknown_role_display(self):
        """测试未知角色使用首字母大写展示"""
        session_data = {
            "messages": [
                {
                    "role": "system",
                    "parts": [{"type": "text", "text": "System notice"}],
                }
            ]
        }

        output = render_session_text("codex://abc", session_data)

        assert "## 1. System" in output
        assert "System notice" in output


class TestRenderSessionHead:
    """测试 render_session_head 函数"""

    def test_render_session_head_renders_common_fields(self):
        output = render_session_head(
            "codex://abc",
            {
                "agent": "Codex",
                "title": "Head Title",
                "created_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
                "cwd_or_project": "/workspace/demo",
                "model": "gpt-5.4",
                "message_count": 3,
                "subtargets": ["worker-a", "worker-b"],
            },
        )

        assert "# Session Head" in output
        assert "URI: codex://abc" in output
        assert "Agent: Codex" in output
        assert "Message Count: 3" in output
        assert "Subtargets: worker-a, worker-b" in output

    def test_render_session_head_truncates_long_values_and_masks_missing(self):
        output = render_session_head(
            "codex://abc",
            {
                "agent": "Codex",
                "title": "A" * 200,
                "created_at": None,
                "updated_at": None,
                "cwd_or_project": "",
                "model": None,
                "message_count": None,
                "subtargets": ["B" * 80],
                "instruction": "C" * 500,
            },
        )

        assert "Title: " + ("A" * 117) + "..." in output
        assert "Created: -" in output
        assert "Model: -" in output
        assert "Subtargets: " + ("B" * 45) + "..." in output
        assert "instruction" not in output

    @pytest.mark.parametrize("language", ALL_LANGUAGES)
    def test_render_session_head_names_an_explicitly_unknown_count(self, language, use_language):
        use_language(language)

        output = render_session_head(
            "codex://abc",
            {
                "message_count": None,
                "message_count_completeness": "unknown",
            },
        )

        assert f"Message Count: {expect(Keys.MESSAGE_COUNT_UNKNOWN)}" in output

    @pytest.mark.parametrize("language", ALL_LANGUAGES)
    def test_metadata_summary_names_an_explicitly_unknown_count(self, language, use_language):
        use_language(language)
        agent = mock.MagicMock()
        agent.get_session_uri.return_value = "codex://abc"
        agent.get_session_summary_fields.return_value = {
            "message_count": None,
            "message_count_completeness": "unknown",
        }

        output = format_session_metadata_summary(agent, make_session("abc", "Title"))

        assert f"msgs={expect(Keys.MESSAGE_COUNT_UNKNOWN)}" in output


class TestTimeHelpers:
    """测试时间相关辅助函数"""

    def test_group_sessions_by_time_all_buckets(self):
        """测试按时间分组包含所有分组与时间戳转换"""
        local_tz = timezone(timedelta(hours=8))
        now_value = datetime(2026, 1, 10, 12, 0, 0, tzinfo=local_tz)

        sessions = [
            make_session(
                "today-dt",
                "Today dt",
                created_at=(now_value - timedelta(hours=1)).astimezone(timezone.utc),
            ),
            make_session("today-sec", "Today sec"),
            make_session("today-ms", "Today ms"),
            make_session(
                "yesterday",
                "Yesterday",
                created_at=(now_value - timedelta(days=1, hours=1)).astimezone(timezone.utc),
            ),
            make_session("week", "Week", created_at=(now_value - timedelta(days=3)).astimezone(timezone.utc)),
            make_session("month", "Month", created_at=(now_value - timedelta(days=20)).astimezone(timezone.utc)),
            make_session("older", "Older", created_at=(now_value - timedelta(days=40)).astimezone(timezone.utc)),
        ]
        sessions[1].created_at = cast(Any, (now_value - timedelta(hours=2)).astimezone(timezone.utc).timestamp())
        sessions[2].created_at = cast(
            Any,
            int((now_value - timedelta(hours=3)).astimezone(timezone.utc).timestamp() * 1000),
        )

        with mock.patch("agent_dump.cli_shared.datetime") as mock_datetime:
            mock_datetime.now.return_value = now_value
            with mock.patch("agent_dump.cli_shared.get_local_timezone", return_value=local_tz):
                groups = group_sessions_by_time(sessions)

        assert set(groups.keys()) == {"今天", "昨天", "本周", "本月", "更早"}
        assert len(groups["今天"]) == 3
        assert len(groups["昨天"]) == 1
        assert len(groups["本周"]) == 1
        assert len(groups["本月"]) == 1
        assert len(groups["更早"]) == 1

    def test_group_sessions_by_time_uses_local_day_boundary(self):
        """测试分组基于本地日界线而不是 UTC"""
        local_tz = timezone(timedelta(hours=8))
        now_value = datetime(2026, 1, 10, 1, 0, 0, tzinfo=local_tz)
        sessions = [
            make_session(
                "today-local",
                "Today local",
                created_at=datetime(2026, 1, 9, 16, 30, 0, tzinfo=timezone.utc),
            ),
            make_session(
                "yesterday-local",
                "Yesterday local",
                created_at=datetime(2026, 1, 8, 16, 30, 0, tzinfo=timezone.utc),
            ),
        ]

        with mock.patch("agent_dump.cli_shared.datetime") as mock_datetime:
            mock_datetime.now.return_value = now_value
            with mock.patch("agent_dump.cli_shared.get_local_timezone", return_value=local_tz):
                groups = group_sessions_by_time(sessions)

        assert [session.id for session in groups["今天"]] == ["today-local"]
        assert [session.id for session in groups["昨天"]] == ["yesterday-local"]


class TestDisplaySessionsList:
    """测试 display_sessions_list 函数"""

    @staticmethod
    def _build_agent():
        agent = mock.MagicMock()
        agent.get_formatted_title.side_effect = lambda session: session.title
        agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
        return agent

    def test_base_agent_formatted_title_uses_local_timezone(self):
        """测试列表展示标题使用本地时区"""
        from agent_dump.agents.codex import CodexAgent

        session = make_session(
            "s-local",
            "Local Session",
            created_at=datetime(2026, 1, 9, 16, 30, 0, tzinfo=timezone.utc),
        )
        with mock.patch("agent_dump.time_utils.get_local_timezone", return_value=timezone(timedelta(hours=8))):
            title = CodexAgent().get_formatted_title(session)

        assert title == "Local Session (2026-01-10 00:30)"

    def test_display_sessions_list_empty(self, capsys):
        """测试空会话列表输出"""
        result = display_sessions_list(self._build_agent(), [])
        assert result is None
        captured = capsys.readouterr()
        assert "(无会话)" in captured.out

    def test_display_sessions_list_shows_every_session_without_reading_input(self, capsys):
        sessions = [make_session(f"s{i}", f"Session {i}") for i in range(3)]

        with mock.patch("builtins.input") as user_input:
            result = display_sessions_list(self._build_agent(), sessions, show_metadata_summary=False)

        assert result is None
        user_input.assert_not_called()
        captured = capsys.readouterr()
        assert all(f"Session {index}" in captured.out for index in range(3))


class TestUriShapesComeFromTheRegistry:
    """AD-140：URI 形状此前硬编码在 uri_support 与 agent_registry 的 if 分支里。

    AGENTS.md §1.3/§3.3 声明 provider schema 只在对应 Agent 内处理、URI scheme 由
    AGENT_REGISTRATIONS 统一声明；那两处 `if scheme == ...` 直接违反了这一点，
    也让新增「session id 带路径前缀」的 provider 必须改共享模块。
    """

    def test_no_provider_name_is_hardcoded_in_uri_parsing(self):
        """parse_uri 不得再出现按 provider 名字分支的代码。"""
        from pathlib import Path

        source = Path("src/agent_dump/uri_support.py").read_text(encoding="utf-8")

        for provider in ("codex", "cursor", "kimi", "claudecode", "opencode", "zcode", "pi"):
            assert f'"{provider}"' not in source, f"uri_support 仍硬编码了 provider 名 {provider!r}"

    def test_no_provider_name_is_hardcoded_in_uri_examples(self):
        from pathlib import Path
        import re

        source = Path("src/agent_dump/agent_registry.py").read_text(encoding="utf-8")
        examples_fn = source[source.index("def get_supported_uri_examples") :]
        examples_fn = examples_fn[: examples_fn.index("\ndef ")] if "\ndef " in examples_fn else examples_fn

        assert not re.search(r'scheme == "', examples_fn), "URI 示例仍按 scheme 名字分支"

    def test_path_prefixes_are_declared_on_the_registration(self):
        from agent_dump.agent_registry import get_uri_path_prefixes

        prefixes = get_uri_path_prefixes()

        assert prefixes["codex"] == ("threads/",)
        assert prefixes["cursor"] == ()

    def test_codex_threads_prefix_still_parses(self):
        assert parse_uri("codex://threads/abc-123") == ("codex", "abc-123")
        assert parse_uri("codex://abc-123") == ("codex", "abc-123")

    def test_empty_id_after_a_prefix_is_rejected(self):
        assert parse_uri("codex://threads/") is None

    def test_prefix_is_only_stripped_for_the_declaring_scheme(self):
        """`threads/` 只对 codex 有意义；其他 provider 不该被剥前缀。"""
        assert parse_uri("kimi://threads/abc") == ("kimi", "threads/abc")

    def test_examples_cover_every_registered_scheme_and_prefix(self):
        from agent_dump.agent_registry import AGENT_REGISTRATIONS, get_supported_uri_examples

        examples = get_supported_uri_examples()

        for registration in AGENT_REGISTRATIONS:
            for scheme in registration.uri_schemes:
                assert f"  - {scheme}://{registration.uri_identifier_label}" in examples
                for prefix in registration.uri_path_prefixes:
                    assert f"  - {scheme}://{prefix}{registration.uri_identifier_label}" in examples

    def test_cursor_example_uses_its_own_identifier_label(self):
        from agent_dump.agent_registry import get_supported_uri_examples

        examples = get_supported_uri_examples()

        assert "  - cursor://<requestid>" in examples
        assert "  - cursor://<session_id>" not in examples

    def test_a_new_prefix_needs_no_change_outside_the_registry(self, monkeypatch):
        """新增带路径前缀的 provider 只该改 registry。"""
        from agent_dump.agent_registry import AGENT_REGISTRATIONS

        patched = tuple(
            (
                type(registration)(
                    factory=registration.factory,
                    uri_schemes=registration.uri_schemes,
                    location_line=registration.location_line,
                    uri_path_prefixes=("runs/",),
                    uri_identifier_label=registration.uri_identifier_label,
                )
                if registration.name == "kimi"
                else registration
            )
            for registration in AGENT_REGISTRATIONS
        )
        monkeypatch.setattr("agent_dump.agent_registry.AGENT_REGISTRATIONS", patched)

        assert parse_uri("kimi://runs/session-9") == ("kimi", "session-9")
