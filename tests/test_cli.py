"""
测试 cli.py 模块
"""

import argparse
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.cli import export_sessions, main, parse_uri, render_session_text


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

            with mock.patch("sys.argv", ["agent-dump", "--list", "--page-size", "1"]):
                main()

            captured = capsys.readouterr()
            assert "Session 1 opencode://s1" in captured.out
            assert "Session 2 opencode://s2" in captured.out
            assert "Session 3 opencode://s3" in captured.out
            assert "第 1/" not in captured.out
            assert "还有" not in captured.out

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

                    with mock.patch("sys.argv", ["agent-dump", "--days", "3"]):
                        main()

            mock_agent.get_sessions.assert_called_once_with(days=3)

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
