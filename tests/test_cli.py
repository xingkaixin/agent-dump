"""
测试 cli.py 模块
"""

import argparse
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.cli import export_sessions, main


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
            mock_scanner.scan.return_value = {}
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump"]):
                main()

            captured = capsys.readouterr()
            assert "未找到任何可用的" in captured.out

    def test_main_list_mode(self, capsys):
        """测试列表模式"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_formatted_title.return_value = "Session Title (2024-01-01)"

            mock_scanner.scan.return_value = {"opencode": [mock.MagicMock()]}
            mock_scanner.get_available_agents.return_value = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list"]):
                main()

            captured = capsys.readouterr()
            assert "OpenCode" in captured.out
            assert "可用的 Agent Tools" in captured.out

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

                    with mock.patch("sys.argv", ["agent-dump"]):
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

                        with mock.patch("sys.argv", ["agent-dump"]):
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

            with mock.patch("sys.argv", ["agent-dump"]):
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

                with mock.patch("sys.argv", ["agent-dump"]):
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

                    with mock.patch("sys.argv", ["agent-dump", "--output", str(output_dir)]):
                        main()

            mock_export.assert_called_once()
            args = mock_export.call_args
            assert str(output_dir) in str(args[0][2])

    def test_main_keyboard_interrupt(self, capsys):
        """测试键盘中断处理"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.scan.side_effect = KeyboardInterrupt()
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump"]):
                # KeyboardInterrupt will propagate since main() doesn't catch it
                with pytest.raises(KeyboardInterrupt):
                    main()
