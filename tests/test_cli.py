"""
测试 cli.py 模块
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.cli import (
    display_sessions_list,
    export_sessions,
    find_session_by_id,
    format_relative_time,
    group_sessions_by_time,
    main,
    parse_uri,
    render_session_text,
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


class TestExportSessions:
    """测试 export_sessions 函数"""

    def test_export_single_session(self, tmp_path):
        """测试导出单个会话"""
        mock_agent = mock.MagicMock()
        mock_agent.name = "test_agent"
        mock_agent.display_name = "Test Agent"

        mock_session = mock.MagicMock()
        mock_session.title = "Test Session"

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
            mock.MagicMock(title="Session 1"),
            mock.MagicMock(title="Session 2"),
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
            mock.MagicMock(title="Session 1"),
            mock.MagicMock(title="Session 2"),
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

        mock_session = mock.MagicMock()
        mock_session.title = "Test Session"

        output_dir = tmp_path / "new_output"
        mock_agent.export_session.return_value = output_dir / "test_agent" / "session.json"

        export_sessions(mock_agent, [mock_session], output_dir)

        assert (output_dir / "test_agent").exists()


class TestMain:
    """测试 main 函数"""

    def test_main_no_agents_available(self, capsys):
        """测试没有可用 agent 时退出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = []
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                main()

            captured = capsys.readouterr()
            assert "未找到任何可用的" in captured.out

    def test_main_uri_mode_codex_threads_variant(self, capsys):
        """测试 URI 模式支持 codex://threads/<id> 变体"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_session_data.return_value = {"messages": []}

            mock_session = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.find_session_by_id") as mock_find:
                mock_find.return_value = (mock_agent, mock_session)

                with mock.patch(
                    "sys.argv",
                    ["agent-dump", "codex://threads/019c8d87-ecc4-7080-bde9-3e257c97cb99"],
                ):
                    result = main()

            assert result == 0
            mock_find.assert_called_once_with(mock_scanner, "019c8d87-ecc4-7080-bde9-3e257c97cb99")

            captured = capsys.readouterr()
            assert "# Session Dump" in captured.out

    def test_main_uri_mode_invalid_uri(self, capsys):
        """测试 URI 模式下无效 URI 会报错"""
        with mock.patch("sys.argv", ["agent-dump", "invalid-uri"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "无效的 URI 格式" in captured.out

    def test_main_uri_mode_no_available_agents(self, capsys):
        """测试 URI 模式下没有可用 agent"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = []
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "codex://session-001"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "未找到任何可用的 Agent Tools 会话" in captured.out

    def test_main_uri_mode_session_not_found(self, capsys):
        """测试 URI 模式下找不到会话"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = [mock.MagicMock()]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.find_session_by_id", return_value=None):
                with mock.patch("sys.argv", ["agent-dump", "codex://session-001"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "未找到会话" in captured.out

    def test_main_uri_mode_scheme_mismatch(self, capsys):
        """测试 URI scheme 与真实会话来源不匹配"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.find_session_by_id") as mock_find:
                mock_find.return_value = (mock_agent, mock.MagicMock())

                with mock.patch("sys.argv", ["agent-dump", "codex://session-001"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "URI scheme 与会话不匹配" in captured.out

    def test_main_uri_mode_get_session_data_failed(self, capsys):
        """测试 URI 模式获取会话数据异常"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_session_data.side_effect = RuntimeError("read error")
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.find_session_by_id") as mock_find:
                mock_find.return_value = (mock_agent, mock.MagicMock())

                with mock.patch("sys.argv", ["agent-dump", "codex://session-001"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "获取会话数据失败" in captured.out

    def test_main_list_mode(self, capsys):
        """测试列表模式"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_formatted_title.return_value = "Session Title (2024-01-01)"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]  # Use get_sessions instead of scan

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list"]):
                main()

            captured = capsys.readouterr()
            assert "OpenCode" in captured.out
            assert "列出" in captured.out  # Updated text

    def test_main_list_mode_no_pagination_prints_all(self, capsys):
        """测试 --list 模式不分页，输出全部会话"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"

            session1 = mock.MagicMock()
            session1.id = "s1"
            session1.title = "Session 1"

            session2 = mock.MagicMock()
            session2.id = "s2"
            session2.title = "Session 2"

            session3 = mock.MagicMock()
            session3.id = "s3"
            session3.title = "Session 3"

            sessions = [session1, session2, session3]
            mock_agent.get_sessions.return_value = sessions
            mock_agent.get_formatted_title.side_effect = lambda session: session.title
            mock_agent.get_session_uri.side_effect = lambda session: f"opencode://{session.id}"

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list", "-page-size", "1"]):
                main()

            captured = capsys.readouterr()
            assert "Session 1 opencode://s1" in captured.out
            assert "Session 2 opencode://s2" in captured.out
            assert "Session 3 opencode://s3" in captured.out
            assert "第 1/" not in captured.out
            assert "还有" not in captured.out

    def test_main_list_mode_no_sessions_for_agent(self, capsys):
        """测试 --list 模式下某 agent 无会话"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "最近 7 天内无会话" in captured.out

    def test_main_list_mode_quit_early_when_display_requests_quit(self, capsys):
        """测试 --list 模式下 display_sessions_list 请求提前退出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.display_sessions_list", return_value=True):
                with mock.patch("sys.argv", ["agent-dump", "--list"]):
                    result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "=" * 60 in captured.out

    def test_main_single_agent_auto_select(self, capsys):
        """测试只有一个 agent 时自动选择"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.cli.export_sessions") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = [Path("test.json")]

                    with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                        main()

            captured = capsys.readouterr()
            assert "自动选择" in captured.out

    def test_main_multiple_agents_interactive_select(self, capsys):
        """测试多个 agent 时交互式选择"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            agent1 = mock.MagicMock()
            agent1.name = "opencode"
            agent1.display_name = "OpenCode"

            agent2 = mock.MagicMock()
            agent2.name = "codex"
            agent2.display_name = "Codex"
            agent2.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.get_available_agents.return_value = [agent1, agent2]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_agent_interactive") as mock_select_agent:
                with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select_session:
                    with mock.patch("agent_dump.cli.export_sessions") as mock_export:
                        mock_select_agent.return_value = agent2
                        mock_select_session.return_value = [mock.MagicMock()]
                        mock_export.return_value = [Path("test.json")]

                        with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                            main()

            captured = capsys.readouterr()
            assert "已选择" in captured.out

    def test_main_multiple_agents_interactive_select_none(self, capsys):
        """测试多 agent 交互选择取消"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            agent1 = mock.MagicMock()
            agent1.display_name = "OpenCode"
            agent2 = mock.MagicMock()
            agent2.display_name = "Codex"
            mock_scanner.get_available_agents.return_value = [agent1, agent2]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_agent_interactive", return_value=None):
                with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "未选择 Agent Tool" in captured.out

    def test_main_no_sessions_found(self, capsys):
        """测试没有找到会话时退出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                main()

            captured = capsys.readouterr()
            assert "未找到" in captured.out

    def test_main_no_sessions_selected(self, capsys):
        """测试没有选择会话时退出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select:
                mock_select.return_value = []

                with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                    main()

            captured = capsys.readouterr()
            assert "未选择会话" in captured.out

    def test_main_with_days_argument(self):
        """测试指定 days 参数"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.cli.export_sessions") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = [Path("test.json")]

                    with mock.patch("sys.argv", ["agent-dump", "-days", "3"]):
                        main()

            mock_agent.get_sessions.assert_called_once_with(days=3)

    def test_main_days_without_mode_auto_switches_to_list(self, capsys):
        """测试仅指定 -days 时自动进入 --list 模式"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "-days", "3"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "列出最近 3 天的会话" in captured.out

    def test_main_query_without_mode_auto_switches_to_list(self, capsys):
        """测试仅指定 -query 时自动进入 --list 模式"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "opencode"
            mock_scanner.agents = [known_agent]

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "-query", "报错"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "匹配「报错」" in captured.out

    def test_main_list_mode_with_query_filters_sessions(self, capsys):
        """测试 --list + -query 会调用过滤逻辑"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "opencode"
            mock_scanner.agents = [known_agent]

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"

            session1 = mock.MagicMock()
            session1.id = "s1"
            session2 = mock.MagicMock()
            session2.id = "s2"
            sessions = [session1, session2]

            mock_agent.get_sessions.return_value = sessions
            mock_agent.get_formatted_title.side_effect = lambda s: f"Session {s.id}"
            mock_agent.get_session_uri.side_effect = lambda s: f"opencode://{s.id}"

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.filter_sessions", return_value=[session2]) as mock_filter:
                with mock.patch("sys.argv", ["agent-dump", "--list", "-query", "error"]):
                    result = main()

        assert result == 0
        mock_filter.assert_called_once_with(mock_agent, sessions, "error")
        captured = capsys.readouterr()
        assert "OpenCode (1 个会话)" in captured.out

    def test_main_multiple_agents_interactive_with_query_scope(self, capsys):
        """测试 interactive + query agent 范围只在指定范围内选择"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_opencode = mock.MagicMock()
            known_opencode.name = "opencode"
            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            known_kimi = mock.MagicMock()
            known_kimi.name = "kimi"
            mock_scanner.agents = [known_opencode, known_codex, known_kimi]

            agent1 = mock.MagicMock()
            agent1.name = "opencode"
            agent1.display_name = "OpenCode"
            agent1.get_sessions.return_value = [mock.MagicMock()]

            agent2 = mock.MagicMock()
            agent2.name = "codex"
            agent2.display_name = "Codex"
            agent2_sessions = [mock.MagicMock()]
            agent2.get_sessions.return_value = agent2_sessions

            agent3 = mock.MagicMock()
            agent3.name = "kimi"
            agent3.display_name = "Kimi"
            agent3_sessions = [mock.MagicMock()]
            agent3.get_sessions.return_value = agent3_sessions

            mock_scanner.get_available_agents.return_value = [agent1, agent2, agent3]
            mock_scanner_class.return_value = mock_scanner

            selected_session = mock.MagicMock()
            with mock.patch("agent_dump.cli.select_agent_interactive", return_value=agent2) as mock_select_agent:
                with mock.patch(
                    "agent_dump.cli.filter_sessions",
                    side_effect=[[selected_session], [mock.MagicMock()]],
                ) as mock_filter:
                    with mock.patch(
                        "agent_dump.cli.select_sessions_interactive",
                        return_value=[selected_session],
                    ):
                        with mock.patch("agent_dump.cli.export_sessions", return_value=[Path("a.json")]):
                            with mock.patch(
                                "sys.argv",
                                ["agent-dump", "--interactive", "-query", "codex,kimi:bug"],
                            ):
                                result = main()

        assert result == 0
        scoped_agents = mock_select_agent.call_args[0][0]
        assert [agent.name for agent in scoped_agents] == ["codex", "kimi"]
        assert mock_select_agent.call_args.kwargs["session_counts"] == {"codex": 1, "kimi": 1}
        assert mock_filter.call_count == 2
        assert mock_filter.call_args_list[0] == mock.call(agent2, agent2_sessions, "bug")
        assert mock_filter.call_args_list[1] == mock.call(agent3, agent3_sessions, "bug")
        captured = capsys.readouterr()
        assert "已选择: Codex" in captured.out

    def test_main_days_and_query_filters_with_and_relation(self):
        """测试 -days 与 -query 同时存在时都会生效"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "opencode"
            mock_scanner.agents = [known_agent]

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            sessions = [mock.MagicMock(), mock.MagicMock()]
            mock_agent.get_sessions.return_value = sessions

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            selected_sessions = [mock.MagicMock()]
            with mock.patch("agent_dump.cli.filter_sessions", return_value=selected_sessions) as mock_filter:
                with mock.patch("agent_dump.cli.select_sessions_interactive", return_value=selected_sessions):
                    with mock.patch("agent_dump.cli.export_sessions", return_value=[Path("a.json")]):
                        with mock.patch(
                            "sys.argv",
                            ["agent-dump", "--interactive", "-days", "3", "-query", "bug"],
                        ):
                            result = main()

        assert result == 0
        mock_agent.get_sessions.assert_called_once_with(days=3)
        mock_filter.assert_called_once_with(mock_agent, sessions, "bug")

    def test_main_invalid_query_with_unknown_agent(self, capsys):
        """测试 query 中包含未知 agent 时返回错误"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_opencode = mock.MagicMock()
            known_opencode.name = "opencode"
            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            mock_scanner.agents = [known_opencode, known_codex]
            mock_scanner.get_available_agents.return_value = [known_opencode]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "-query", "codex,unknown:bug"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "无效的 -query 参数" in captured.out

    def test_main_interactive_query_no_match_returns_1(self, capsys):
        """测试 interactive + query 全部无命中时返回 1"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            known_kimi = mock.MagicMock()
            known_kimi.name = "kimi"
            mock_scanner.agents = [known_codex, known_kimi]

            agent_codex = mock.MagicMock()
            agent_codex.name = "codex"
            agent_codex.display_name = "Codex"
            agent_codex.get_sessions.return_value = [mock.MagicMock()]

            agent_kimi = mock.MagicMock()
            agent_kimi.name = "kimi"
            agent_kimi.display_name = "Kimi"
            agent_kimi.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.get_available_agents.return_value = [agent_codex, agent_kimi]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.filter_sessions", side_effect=[[], []]) as mock_filter:
                with mock.patch("agent_dump.cli.select_agent_interactive") as mock_select_agent:
                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "-query", "codex,kimi:bug"]):
                        result = main()

        assert result == 1
        assert mock_filter.call_count == 2
        mock_select_agent.assert_not_called()
        captured = capsys.readouterr()
        assert "未找到最近 7 天内匹配「bug」的会话" in captured.out

    def test_main_interactive_query_auto_selects_only_matched_agent(self, capsys):
        """测试 interactive + query 仅一个 agent 命中时自动选择"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            known_kimi = mock.MagicMock()
            known_kimi.name = "kimi"
            mock_scanner.agents = [known_codex, known_kimi]

            agent_codex = mock.MagicMock()
            agent_codex.name = "codex"
            agent_codex.display_name = "Codex"
            codex_sessions = [mock.MagicMock()]
            agent_codex.get_sessions.return_value = codex_sessions

            agent_kimi = mock.MagicMock()
            agent_kimi.name = "kimi"
            agent_kimi.display_name = "Kimi"
            kimi_sessions = [mock.MagicMock()]
            agent_kimi.get_sessions.return_value = kimi_sessions

            mock_scanner.get_available_agents.return_value = [agent_codex, agent_kimi]
            mock_scanner_class.return_value = mock_scanner

            selected_session = mock.MagicMock()
            with mock.patch(
                "agent_dump.cli.filter_sessions",
                side_effect=[[selected_session], []],
            ) as mock_filter:
                with mock.patch("agent_dump.cli.select_agent_interactive") as mock_select_agent:
                    with mock.patch(
                        "agent_dump.cli.select_sessions_interactive",
                        return_value=[selected_session],
                    ):
                        with mock.patch("agent_dump.cli.export_sessions", return_value=[Path("a.json")]):
                            with mock.patch("sys.argv", ["agent-dump", "--interactive", "-query", "codex,kimi:bug"]):
                                result = main()

        assert result == 0
        assert mock_filter.call_count == 2
        assert mock_filter.call_args_list[0] == mock.call(agent_codex, codex_sessions, "bug")
        assert mock_filter.call_args_list[1] == mock.call(agent_kimi, kimi_sessions, "bug")
        mock_select_agent.assert_not_called()
        captured = capsys.readouterr()
        assert "自动选择: Codex" in captured.out

    def test_main_with_output_argument(self, tmp_path):
        """测试指定 output 参数"""
        output_dir = tmp_path / "custom_output"

        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.cli.export_sessions") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = [Path("test.json")]

                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "--output", str(output_dir)]):
                        main()

            mock_export.assert_called_once()
            args = mock_export.call_args
            assert str(output_dir) in str(args[0][2])

    def test_main_with_output_short_argument(self, tmp_path):
        """测试指定 -output 参数"""
        output_dir = tmp_path / "custom_output"

        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.cli.export_sessions") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = [Path("test.json")]

                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "-output", str(output_dir)]):
                        main()

            mock_export.assert_called_once()
            args = mock_export.call_args
            assert str(output_dir) in str(args[0][2])

    def test_main_interactive_with_format_long_alias_md(self):
        """测试 --format md 会走 Markdown 导出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.cli.export_sessions") as mock_export_json:
                    with mock.patch("agent_dump.cli.export_sessions_markdown") as mock_export_md:
                        mock_select.return_value = [mock.MagicMock()]
                        mock_export_md.return_value = [Path("test.md")]

                        with mock.patch("sys.argv", ["agent-dump", "--interactive", "--format", "md"]):
                            result = main()

        assert result == 0
        mock_export_md.assert_called_once()
        mock_export_json.assert_not_called()

    def test_main_interactive_with_format_print_returns_1(self, capsys):
        """测试 --interactive + -format print 返回错误"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--interactive", "-format", "print"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "--interactive 模式仅支持 json 或 md" in captured.out

    def test_main_list_mode_warns_and_continues_when_format_specified(self, capsys):
        """测试 --list + -format 会警告但继续"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list", "-format", "md"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "--list 模式会忽略 -format/--format 参数" in captured.out

    def test_main_list_mode_warns_and_continues_when_output_specified(self, capsys, tmp_path):
        """测试 --list + -output 会警告但继续"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list", "-output", str(tmp_path / "x")]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "--list 模式会忽略 -output/--output 参数" in captured.out

    def test_main_uri_mode_json_writes_file_and_not_print_body(self, capsys, tmp_path):
        """测试 URI + --format json 写文件且不输出正文"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output_dir = output_root / "codex"
            expected_output = expected_output_dir / "session-001.json"
            mock_agent.export_session.return_value = expected_output

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "sys.argv",
                    ["agent-dump", "codex://session-001", "--format", "json", "--output", str(output_root)],
                ):
                    result = main()

        assert result == 0
        mock_agent.export_session.assert_called_once_with(mock_session, expected_output_dir)
        captured = capsys.readouterr()
        assert "# Session Dump" not in captured.out
        assert str(expected_output) in captured.out

    def test_main_uri_mode_md_writes_file_and_not_print_body(self, capsys, tmp_path):
        """测试 URI + -format md 写文件且不输出正文"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_session_data.return_value = {
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}]
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.md"

            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "sys.argv",
                    ["agent-dump", "codex://session-001", "-format", "md", "-output", str(output_root)],
                ):
                    result = main()

        assert result == 0
        assert expected_output.exists()
        assert "Hello" in expected_output.read_text(encoding="utf-8")
        captured = capsys.readouterr()
        assert "## 1. User" not in captured.out
        assert str(expected_output) in captured.out

    def test_main_keyboard_interrupt(self, capsys):
        """测试键盘中断处理"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.side_effect = KeyboardInterrupt()
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                # KeyboardInterrupt will propagate since main() doesn't catch it
                with pytest.raises(KeyboardInterrupt):
                    main()

    def test_main_no_flags_prints_help(self, capsys):
        """测试无参数时打印帮助并返回 None"""
        with mock.patch("sys.argv", ["agent-dump"]):
            result = main()

        assert result is None
        captured = capsys.readouterr()
        assert "usage:" in captured.out

    def test_main_warns_when_too_many_sessions(self, capsys):
        """测试会话数量超过 100 时提示缩小范围"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock() for _ in range(101)]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.cli.export_sessions") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = [Path("a.json")]

                    with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                        result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "会话数量较多" in captured.out


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


class TestTimeHelpers:
    """测试时间相关辅助函数"""

    @staticmethod
    def _format_with_fixed_now(time_value, now_value):
        with mock.patch("agent_dump.cli.datetime") as mock_datetime:
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
        now_value = datetime(2026, 1, 10, 12, 0, 0)

        sessions = [
            mock.MagicMock(id="today-dt", created_at=now_value - timedelta(hours=1)),
            mock.MagicMock(id="today-sec", created_at=(now_value - timedelta(hours=2)).timestamp()),
            mock.MagicMock(id="today-ms", created_at=int((now_value - timedelta(hours=3)).timestamp() * 1000)),
            mock.MagicMock(id="yesterday", created_at=now_value - timedelta(days=1, hours=1)),
            mock.MagicMock(id="week", created_at=now_value - timedelta(days=3)),
            mock.MagicMock(id="month", created_at=now_value - timedelta(days=20)),
            mock.MagicMock(id="older", created_at=now_value - timedelta(days=40)),
        ]

        with mock.patch("agent_dump.cli.datetime") as mock_datetime:
            mock_datetime.now.return_value = now_value
            mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp
            groups = group_sessions_by_time(sessions)

        assert set(groups.keys()) == {"今天", "昨天", "本周", "本月", "更早"}
        assert len(groups["今天"]) == 3
        assert len(groups["昨天"]) == 1
        assert len(groups["本周"]) == 1
        assert len(groups["本月"]) == 1
        assert len(groups["更早"]) == 1


class TestDisplaySessionsList:
    """测试 display_sessions_list 函数"""

    @staticmethod
    def _build_agent():
        agent = mock.MagicMock()
        agent.get_formatted_title.side_effect = lambda session: session.title
        agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
        return agent

    def test_display_sessions_list_empty(self, capsys):
        """测试空会话列表输出"""
        result = display_sessions_list(self._build_agent(), [], page_size=2)
        assert result is False
        captured = capsys.readouterr()
        assert "(无会话)" in captured.out

    def test_display_sessions_list_quit_on_q(self, capsys):
        """测试分页模式输入 q 退出"""
        sessions = [mock.MagicMock(id=f"s{i}", title=f"Session {i}") for i in range(3)]

        with mock.patch("builtins.input", return_value="q"):
            result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=True)

        assert result is True
        captured = capsys.readouterr()
        assert "第 1/2 页" in captured.out

    def test_display_sessions_list_handles_eof_interrupt(self, capsys):
        """测试分页模式处理 EOFError"""
        sessions = [mock.MagicMock(id=f"s{i}", title=f"Session {i}") for i in range(3)]

        with mock.patch("builtins.input", side_effect=EOFError):
            result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=True)

        assert result is True
        captured = capsys.readouterr()
        assert "按 Enter 查看更多" in captured.out

    def test_display_sessions_list_show_all_pages(self, capsys):
        """测试分页模式翻页直到结束"""
        sessions = [mock.MagicMock(id=f"s{i}", title=f"Session {i}") for i in range(3)]

        with mock.patch("builtins.input", return_value=""):
            result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=True)

        assert result is False
        captured = capsys.readouterr()
        assert "已显示全部会话" in captured.out

    def test_display_sessions_list_non_pagination_shows_remaining_hint(self, capsys):
        """测试非分页模式提示剩余会话数"""
        sessions = [mock.MagicMock(id=f"s{i}", title=f"Session {i}") for i in range(3)]
        result = display_sessions_list(self._build_agent(), sessions, page_size=2, show_pagination=False)

        assert result is False
        captured = capsys.readouterr()
        assert "还有 1 个会话未显示" in captured.out
