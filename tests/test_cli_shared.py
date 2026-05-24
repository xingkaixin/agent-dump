"""
测试 CLI 共享辅助模块
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.cli_shared import (
    collect_query_matches,
    collect_search_matches,
    display_search_results,
    display_sessions_list,
    export_sessions,
    export_sessions_for_formats,
    find_session_by_id,
    format_relative_time,
    group_sessions_by_time,
    parse_format_spec,
    parse_uri,
    render_query_summary,
    render_session_head,
    render_session_text,
)
from agent_dump.query_filter import QuerySpec, SearchSessionMatch


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
        agent_names=agent_names,
        keyword=keyword,
        project_path=project_path,
        roles=roles,
        limit=limit,
    )


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

        with mock.patch("agent_dump.cli_shared.filter_sessions_by_query", side_effect=[[older], [newer]]):
            matched = collect_query_matches([agent_a, agent_b], days=7, spec=make_query_spec(keyword="bug", limit=1))

        assert {name: [session.id for session in sessions] for name, sessions in matched.items()} == {
            "kimi": ["s-new"]
        }

    def test_collect_search_matches_applies_global_rank_sort_and_limit(self):
        older = make_session("s-old", "old", created_at=datetime(2026, 1, 1, 10, 0, 0))
        newer = make_session("s-new", "new", created_at=datetime(2026, 1, 1, 11, 0, 0))

        agent_a = mock.MagicMock()
        agent_a.name = "codex"
        agent_a.get_sessions.return_value = [older]

        agent_b = mock.MagicMock()
        agent_b.name = "kimi"
        agent_b.get_sessions.return_value = [newer]

        match_a = SearchSessionMatch(agent=agent_a, session=older, snippet="old", rank=0.5)
        match_b = SearchSessionMatch(agent=agent_b, session=newer, snippet="new", rank=2.0)

        with mock.patch("agent_dump.cli_shared.search_sessions_by_query", side_effect=[[match_a], [match_b]]):
            result = collect_search_matches([agent_a, agent_b], days=7, spec=make_query_spec(keyword="bug", limit=1))

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

class TestFindSessionById:
    """测试 find_session_by_id 函数"""

    def test_find_session_by_id_found(self):
        """测试跨 agent 查找命中会话"""
        scanner = mock.MagicMock()

        agent1 = mock.MagicMock()
        agent1.get_sessions.return_value = [mock.MagicMock(id="s1"), mock.MagicMock(id="s2")]

        target_session = mock.MagicMock(id="target")
        agent2 = mock.MagicMock()
        agent2.get_sessions.return_value = [target_session]

        scanner.get_available_agents.return_value = [agent1, agent2]

        result = find_session_by_id(scanner, "target")

        assert result == (agent2, target_session)
        agent1.get_sessions.assert_called_once_with(days=3650)
        agent2.get_sessions.assert_called_once_with(days=3650)

    def test_find_session_by_id_not_found(self):
        """测试找不到会话时返回 None"""
        scanner = mock.MagicMock()
        agent = mock.MagicMock()
        agent.get_sessions.return_value = [mock.MagicMock(id="s1")]
        scanner.get_available_agents.return_value = [agent]

        result = find_session_by_id(scanner, "missing")

        assert result is None

    def test_find_session_by_id_limits_to_agent_name(self):
        scanner = mock.MagicMock()
        codex_agent = mock.MagicMock()
        codex_agent.name = "codex"
        opencode_agent = mock.MagicMock()
        opencode_agent.name = "opencode"
        target_session = mock.MagicMock(id="target")
        opencode_agent.get_sessions.return_value = [target_session]
        scanner.get_available_agents.return_value = [codex_agent, opencode_agent]

        result = find_session_by_id(scanner, "target", agent_name="opencode")

        assert result == (opencode_agent, target_session)
        codex_agent.get_sessions.assert_not_called()
        opencode_agent.get_sessions.assert_called_once_with(days=3650)

    def test_find_session_by_id_cursor_matches_request_id(self):
        """测试 Cursor 会按 metadata.request_id 命中"""
        scanner = mock.MagicMock()
        cursor_agent = mock.MagicMock()
        cursor_agent.name = "cursor"
        session = mock.MagicMock(id="composer-like-id")
        session.metadata = {"request_id": "request-xyz"}
        cursor_agent.get_sessions.return_value = [session]
        scanner.get_available_agents.return_value = [cursor_agent]

        result = find_session_by_id(scanner, "request-xyz")
        assert result == (cursor_agent, session)

class TestExportSessions:
    """测试 export_sessions 函数"""

    def test_export_single_session(self, tmp_path):
        """测试导出单个会话"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"

        mock_session = make_session("session-001", "Test Session")

        mock_agent.export_session.return_value = tmp_path / "test_agent" / "session-001.json"

        result = export_sessions(mock_agent, [mock_session], tmp_path)

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

        result = export_sessions(mock_agent, sessions, tmp_path)

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

        result = export_sessions(mock_agent, sessions, tmp_path)

        assert len(result) == 1
        captured = capsys.readouterr()
        assert "错误" in captured.out or "Export failed" in captured.out

    def test_export_creates_directory(self, tmp_path):
        """测试导出时创建输出目录"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"

        mock_session = make_session("session-001", "Test Session")

        output_dir = tmp_path / "new_output"
        mock_agent.export_session.return_value = output_dir / "test_agent" / "session.json"

        export_sessions(mock_agent, [mock_session], output_dir)

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

class TestFormatSpec:
    """测试格式解析辅助函数"""

    def test_parse_format_spec_supports_alias_and_dedup(self):
        result = parse_format_spec("json, md ,raw,json")
        assert result == ["json", "markdown", "raw"]

    def test_parse_format_spec_rejects_unknown_format(self):
        with pytest.raises(ValueError):
            parse_format_spec("json,foo")

    def test_parse_format_spec_rejects_empty_part(self):
        with pytest.raises(ValueError):
            parse_format_spec("json,,raw")

class TestRenderSessionText:
    """测试 render_session_text 函数"""

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

class TestTimeHelpers:
    """测试时间相关辅助函数"""

    @staticmethod
    def _format_with_fixed_now(time_value, now_value):
        with mock.patch("agent_dump.cli_shared.datetime") as mock_datetime:
            mock_datetime.now.return_value = now_value
            mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp
            return format_relative_time(time_value)

    def test_format_relative_time_just_now(self):
        """测试刚刚分支"""
        now_value = datetime(2026, 1, 1, 12, 0, 0)
        result = self._format_with_fixed_now(now_value, now_value)
        assert result == "刚刚"

    def test_format_relative_time_minutes_with_timestamp(self):
        """测试分钟分支（数字时间戳输入）"""
        now_value = datetime(2026, 1, 1, 12, 0, 0)
        seconds_ts = (now_value - timedelta(minutes=5)).timestamp()
        result = self._format_with_fixed_now(seconds_ts, now_value)
        assert result == "5 分钟前"

    def test_format_relative_time_hours(self):
        """测试小时分支"""
        now_value = datetime(2026, 1, 1, 12, 0, 0)
        result = self._format_with_fixed_now(now_value - timedelta(hours=3), now_value)
        assert result == "3 小时前"

    def test_format_relative_time_yesterday(self):
        """测试昨天分支"""
        now_value = datetime(2026, 1, 10, 12, 0, 0)
        result = self._format_with_fixed_now(now_value - timedelta(days=1), now_value)
        assert result == "昨天"

    def test_format_relative_time_days(self):
        """测试天分支"""
        now_value = datetime(2026, 1, 10, 12, 0, 0)
        result = self._format_with_fixed_now(now_value - timedelta(days=3), now_value)
        assert result == "3 天前"

    def test_format_relative_time_weeks(self):
        """测试周分支"""
        now_value = datetime(2026, 2, 1, 12, 0, 0)
        result = self._format_with_fixed_now(now_value - timedelta(days=14), now_value)
        assert result == "2 周前"

    def test_format_relative_time_date(self):
        """测试日期分支"""
        now_value = datetime(2026, 2, 1, 12, 0, 0)
        old_time = now_value - timedelta(days=40)
        result = self._format_with_fixed_now(old_time, now_value)
        assert result == old_time.strftime("%Y-%m-%d")

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
        setattr(sessions[1], "created_at", (now_value - timedelta(hours=2)).astimezone(timezone.utc).timestamp())
        setattr(
            sessions[2],
            "created_at",
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
        result = display_sessions_list(self._build_agent(), [], page_size=2)
        assert result is False
        captured = capsys.readouterr()
        assert "(无会话)" in captured.out

    def test_display_sessions_list_quit_on_q(self, capsys):
        """测试分页模式输入 q 退出"""
        sessions = [make_session(f"s{i}", f"Session {i}") for i in range(3)]

        with mock.patch("builtins.input", return_value="q"):
            result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=True)

        assert result is True
        captured = capsys.readouterr()
        assert "第 1/2 页" in captured.out

    def test_display_sessions_list_handles_eof_interrupt(self, capsys):
        """测试分页模式处理 EOFError"""
        sessions = [make_session(f"s{i}", f"Session {i}") for i in range(3)]

        with mock.patch("builtins.input", side_effect=EOFError):
            result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=True)

        assert result is True
        captured = capsys.readouterr()
        assert "按 Enter 查看更多" in captured.out

    def test_display_sessions_list_show_all_pages(self, capsys):
        """测试分页模式翻页直到结束"""
        sessions = [make_session(f"s{i}", f"Session {i}") for i in range(3)]

        with mock.patch("builtins.input", return_value=""):
            result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=True)

        assert result is False
        captured = capsys.readouterr()
        assert "已显示全部会话" in captured.out

    def test_display_sessions_list_non_pagination_shows_remaining_hint(self, capsys):
        """测试非分页模式提示剩余会话数"""
        sessions = [make_session(f"s{i}", f"Session {i}") for i in range(3)]
        result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=False)

        assert result is False
        captured = capsys.readouterr()
        assert "还有 1 个会话未显示" in captured.out
