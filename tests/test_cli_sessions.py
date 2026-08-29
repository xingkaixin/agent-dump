"""Session listing and interactive selection CLI tests."""

from pathlib import Path
import sys
from unittest import mock

from cli_test_support import (
    configure_scanner_sessions,
    make_export_result,
)
from locale_helpers import Keys as LocaleKeys, expect
import pytest

from agent_dump.cli import (
    main,
)


class TestMain:
    def test_main_no_agents_available(self, capsys):
        """测试没有可用 agent 时退出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = []
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                main()

            captured = capsys.readouterr()
            assert "未找到任何可用的" in captured.out
            assert "CODEX_HOME/sessions" in captured.out
            assert "KIMI_SHARE_DIR/sessions" in captured.out
            assert "CLAUDE_CONFIG_DIR/projects" in captured.out
            assert "XDG/LOCALAPPDATA opencode.db" in captured.out
            if sys.platform.startswith(("darwin", "win")):
                assert ".zcode/cli/db/db.sqlite" in captured.out
            else:
                assert "ZCode:" not in captured.out

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

            configure_scanner_sessions(mock_scanner)
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
            mock_agent.get_session_summary_fields.return_value = {
                "cwd_project": "/workspace/demo",
                "model": "gpt-5",
                "message_count": 2,
                "updated_at": "2024-01-01 12:00",
            }

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with (
                mock.patch("sys.argv", ["agent-dump", "--list", "-page-size", "1"]),
                mock.patch("builtins.input") as user_input,
            ):
                main()

            captured = capsys.readouterr()
            user_input.assert_not_called()
            assert "• Session 1" in captured.out
            assert "uri=opencode://s1" in captured.out
            assert "model=gpt-5" in captured.out
            assert "• Session 2" in captured.out
            assert "uri=opencode://s2" in captured.out
            assert "• Session 3" in captured.out
            assert "uri=opencode://s3" in captured.out
            assert "第 1/" not in captured.out
            assert "还有" not in captured.out

    def test_main_list_mode_can_hide_metadata_summary(self, capsys):
        """测试 --no-metadata-summary 可关闭摘要展示"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"

            session = mock.MagicMock()
            session.id = "s1"
            session.title = "Session 1"

            mock_agent.get_sessions.return_value = [session]
            mock_agent.get_formatted_title.return_value = "Session 1"
            mock_agent.get_session_uri.return_value = "opencode://s1"

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list", "--no-metadata-summary"]):
                main()

        captured = capsys.readouterr()
        assert "Session 1 opencode://s1" in captured.out
        assert "uri=opencode://s1" not in captured.out

    def test_main_list_mode_no_sessions_for_agent(self, capsys):
        """测试 --list 模式下某 agent 无会话"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "最近 7 天内无会话" in captured.out

    def test_main_list_mode_shows_cursor_uri(self, capsys):
        """测试 --list 模式可展示 Cursor URI"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "cursor"
            mock_agent.display_name = "Cursor"
            session = mock.MagicMock()
            session.id = "request-001"
            mock_agent.get_sessions.return_value = [session]
            mock_agent.get_formatted_title.return_value = "Cursor Session"
            mock_agent.get_session_uri.return_value = "cursor://request-001"
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "cursor://request-001" in captured.out

    def test_main_list_mode_quit_early_when_display_requests_quit(self, capsys):
        """测试 --list 模式下 display_sessions_list 请求提前退出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.display_sessions_list", return_value=True):
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

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(Path("test.json"))

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

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_agent_interactive") as mock_select_agent:
                with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select_session:
                    with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                        mock_select_agent.return_value = agent2
                        mock_select_session.return_value = [mock.MagicMock()]
                        mock_export.return_value = make_export_result(Path("test.json"))

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
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_agent_interactive", return_value=None):
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

            configure_scanner_sessions(mock_scanner)
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

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
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

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(Path("test.json"))

                    with mock.patch("sys.argv", ["agent-dump", "-days", "3"]):
                        main()

            mock_agent.get_sessions.assert_called_once_with(days=3)

    @pytest.mark.parametrize("days", [3, 7])
    def test_main_days_without_mode_auto_switches_to_list(self, capsys, days):
        """测试仅指定 -days 时自动进入 --list 模式"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "-days", str(days)]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert f"列出最近 {days} 天的会话" in captured.out

    def test_main_rejects_days_outside_calendar_range(self, capsys):
        with mock.patch("sys.argv", ["agent-dump", "-days", "0"]):
            with pytest.raises(SystemExit):
                main()

        assert expect(LocaleKeys.CLI_DAYS_INVALID, value=0) in capsys.readouterr().err

    def test_main_warns_when_too_many_sessions(self, capsys):
        """测试会话数量超过 100 时提示缩小范围"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock() for _ in range(101)]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(Path("a.json"))

                    with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                        result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "会话数量较多" in captured.out
