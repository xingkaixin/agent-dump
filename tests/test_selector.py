"""
测试 selector.py 模块
"""

from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.selector import (
    is_terminal,
    select_agent_interactive,
    select_agent_simple,
    select_sessions_interactive,
    select_sessions_simple,
)
from agent_dump.agents.base import Session


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing"""
    agent = mock.MagicMock()
    agent.name = "test_agent"
    agent.display_name = "Test Agent"
    agent.get_formatted_title = lambda s: f"{s.title} ({s.created_at.strftime('%Y-%m-%d %H:%M')})"
    return agent


@pytest.fixture
def sample_sessions():
    """Create sample sessions for testing"""
    return [
        Session(
            id="session-001",
            title="Test Session 1",
            created_at=datetime(2024, 1, 1, 10, 0, 0),
            updated_at=datetime(2024, 1, 1, 10, 30, 0),
            source_path=Path("/test/path"),
            metadata={},
        ),
        Session(
            id="session-002",
            title="Test Session 2",
            created_at=datetime(2024, 1, 2, 14, 0, 0),
            updated_at=datetime(2024, 1, 2, 14, 30, 0),
            source_path=Path("/test/path"),
            metadata={},
        ),
    ]


class TestIsTerminal:
    """测试 is_terminal 函数"""

    def test_is_terminal_true(self):
        """测试在终端环境中返回 True"""
        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch("sys.stdout.isatty", return_value=True):
                assert is_terminal() is True

    def test_is_terminal_false_stdin_not_tty(self):
        """测试 stdin 不是 TTY 时返回 False"""
        with mock.patch("sys.stdin.isatty", return_value=False):
            with mock.patch("sys.stdout.isatty", return_value=True):
                assert is_terminal() is False

    def test_is_terminal_false_stdout_not_tty(self):
        """测试 stdout 不是 TTY 时返回 False"""
        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch("sys.stdout.isatty", return_value=False):
                assert is_terminal() is False


class TestSelectAgentSimple:
    """测试 select_agent_simple 函数"""

    def test_select_single_agent(self, mock_agent):
        """测试选择单个 agent"""
        mock_agent.get_sessions.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", return_value="1"):
            result = select_agent_simple(agents)

        assert result == mock_agent

    def test_select_invalid_index(self, mock_agent, capsys):
        """测试选择无效索引"""
        mock_agent.get_sessions.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", return_value="5"):
            result = select_agent_simple(agents)

        assert result is None

    def test_select_invalid_input(self, mock_agent, capsys):
        """测试无效输入"""
        mock_agent.get_sessions.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", return_value="invalid"):
            result = select_agent_simple(agents)

        assert result is None

    def test_select_eof_error(self, mock_agent, capsys):
        """测试 EOF 错误处理"""
        mock_agent.get_sessions.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", side_effect=EOFError()):
            result = select_agent_simple(agents)

        assert result is None

    def test_select_agent_simple_uses_precomputed_session_counts(self, mock_agent):
        """测试简单模式使用 session_counts 时不调用 get_sessions"""
        agents = [mock_agent]

        with mock.patch("builtins.input", return_value="1"):
            result = select_agent_simple(agents, days=7, session_counts={"test_agent": 5})

        assert result == mock_agent
        mock_agent.get_sessions.assert_not_called()


class TestSelectSessionsSimple:
    """测试 select_sessions_simple 函数"""

    def test_select_all_sessions(self, mock_agent, sample_sessions, capsys):
        """测试选择所有会话"""
        with mock.patch("builtins.input", return_value="all"):
            result = select_sessions_simple(sample_sessions, mock_agent)

        assert len(result) == 2
        assert result[0].id == "session-001"
        assert result[1].id == "session-002"

    def test_select_specific_sessions(self, mock_agent, sample_sessions, capsys):
        """测试通过索引选择特定会话"""
        with mock.patch("builtins.input", return_value="1,2"):
            result = select_sessions_simple(sample_sessions, mock_agent)

        assert len(result) == 2
        assert result[0].id == "session-001"
        assert result[1].id == "session-002"

    def test_select_single_session(self, mock_agent, sample_sessions, capsys):
        """测试选择单个会话"""
        with mock.patch("builtins.input", return_value="2"):
            result = select_sessions_simple(sample_sessions, mock_agent)

        assert len(result) == 1
        assert result[0].id == "session-002"

    def test_select_out_of_range(self, mock_agent, sample_sessions, capsys):
        """测试选择超出范围的索引"""
        with mock.patch("builtins.input", return_value="1,5,10"):
            result = select_sessions_simple(sample_sessions, mock_agent)

        # 只有第一个有效
        assert len(result) == 1
        assert result[0].id == "session-001"

    def test_select_invalid_input(self, mock_agent, sample_sessions, capsys):
        """测试无效输入"""
        with mock.patch("builtins.input", return_value="invalid"):
            result = select_sessions_simple(sample_sessions, mock_agent)

        assert result == []

    def test_select_eof_error(self, mock_agent, sample_sessions, capsys):
        """测试 EOF 错误处理"""
        with mock.patch("builtins.input", side_effect=EOFError()):
            result = select_sessions_simple(sample_sessions, mock_agent)

        assert result == []

    def test_select_empty_sessions(self, mock_agent, capsys):
        """测试空会话列表"""
        with mock.patch("builtins.input", return_value=""):
            result = select_sessions_simple([], mock_agent)
        assert result == []


class TestSelectAgentInteractive:
    """测试 select_agent_interactive 函数"""

    def test_empty_agents(self, capsys):
        """测试空 agent 列表"""
        result = select_agent_interactive([])
        assert result is None
        captured = capsys.readouterr()
        assert "没有可用的 Agent Tools" in captured.out

    def test_non_terminal_uses_simple_mode(self, mock_agent):
        """测试非终端环境使用简单模式"""
        agents = [mock_agent]

        with mock.patch("agent_dump.selector.is_terminal", return_value=False):
            with mock.patch("agent_dump.selector.select_agent_simple") as mock_simple:
                mock_simple.return_value = mock_agent
                result = select_agent_interactive(agents)

        mock_simple.assert_called_once_with(agents, days=7, session_counts=None)
        assert result == mock_agent

    def test_terminal_interactive_selection(self, mock_agent):
        """测试终端环境交互式选择"""
        agents = [mock_agent]

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.select") as mock_select:
                mock_select.return_value.ask.return_value = mock_agent
                result = select_agent_interactive(agents)

        assert result == mock_agent

    def test_terminal_keyboard_interrupt(self, mock_agent, capsys):
        """测试终端环境键盘中断"""
        agents = [mock_agent]

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.select") as mock_select:
                mock_select.return_value.ask.side_effect = KeyboardInterrupt()
                result = select_agent_interactive(agents)

        assert result is None
        captured = capsys.readouterr()
        assert "用户取消操作" in captured.out

    def test_q_key_exit(self, mock_agent):
        """测试按 q 键退出"""
        agents = [mock_agent]

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.select") as mock_select:
                mock_select.return_value.ask.return_value = None
                result = select_agent_interactive(agents)

        assert result is None


class TestSelectSessionsInteractive:
    """测试 select_sessions_interactive 函数"""

    def test_empty_sessions(self, mock_agent, capsys):
        """测试空会话列表"""
        result = select_sessions_interactive([], mock_agent)
        assert result == []
        captured = capsys.readouterr()
        assert "No sessions found" in captured.out

    def test_non_terminal_uses_simple_mode(self, mock_agent, sample_sessions):
        """测试非终端环境使用简单模式"""
        with mock.patch("agent_dump.selector.is_terminal", return_value=False):
            with mock.patch("agent_dump.selector.select_sessions_simple") as mock_simple:
                mock_simple.return_value = sample_sessions[:1]
                result = select_sessions_interactive(sample_sessions, mock_agent)

        mock_simple.assert_called_once_with(sample_sessions, mock_agent)
        assert result == sample_sessions[:1]

    def test_terminal_interactive_selection(self, mock_agent, sample_sessions):
        """测试终端环境交互式选择"""
        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox") as mock_checkbox:
                mock_checkbox.return_value.ask.return_value = sample_sessions
                result = select_sessions_interactive(sample_sessions, mock_agent)

        assert result == sample_sessions

    def test_terminal_keyboard_interrupt(self, mock_agent, sample_sessions, capsys):
        """测试终端环境键盘中断"""
        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox") as mock_checkbox:
                mock_checkbox.return_value.ask.side_effect = KeyboardInterrupt()
                result = select_sessions_interactive(sample_sessions, mock_agent)

        assert result == []
        captured = capsys.readouterr()
        assert "用户取消操作" in captured.out

    def test_q_key_exit_returns_empty_list(self, mock_agent, sample_sessions):
        """测试按 q 键退出返回空列表"""
        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox") as mock_checkbox:
                mock_checkbox.return_value.ask.return_value = None
                result = select_sessions_interactive(sample_sessions, mock_agent)

        assert result == []

    def test_long_title_truncation(self, mock_agent):
        """测试长标题截断"""
        sessions = [
            Session(
                id="test",
                title="A" * 100,
                created_at=datetime(2024, 1, 1, 10, 0, 0),
                updated_at=datetime(2024, 1, 1, 10, 0, 0),
                source_path=Path("/test"),
                metadata={},
            )
        ]

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox") as mock_checkbox:
                mock_checkbox.return_value.ask.return_value = sessions
                result = select_sessions_interactive(sessions, mock_agent)

        assert result == sessions


class TestSelectAgentInteractiveEdgeCases:
    """测试 select_agent_interactive 边界情况"""

    def test_agent_scan_count_display(self, mock_agent):
        """测试显示 agent 的会话数量"""
        mock_agent.get_sessions.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        agents = [mock_agent]

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.select") as mock_select:
                with mock.patch("questionary.Choice") as mock_choice:
                    mock_choice.return_value = mock.MagicMock()
                    mock_select.return_value.ask.return_value = mock_agent
                    select_agent_interactive(agents)

        # Verify Choice was called with correct label format
        mock_choice.assert_called_once()
        call_args = mock_choice.call_args
        assert "3 个会话" in call_args.kwargs.get("title", "") or any("3 个会话" in str(arg) for arg in call_args.args)

    def test_agent_count_uses_precomputed_session_counts(self, mock_agent):
        """测试传入 session_counts 时不再调用 get_sessions"""
        agents = [mock_agent]

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.select") as mock_select:
                with mock.patch("questionary.Choice") as mock_choice:
                    mock_choice.return_value = mock.MagicMock()
                    mock_select.return_value.ask.return_value = mock_agent
                    select_agent_interactive(
                        agents,
                        days=7,
                        session_counts={"test_agent": 2},
                    )

        mock_agent.get_sessions.assert_not_called()
        call_args = mock_choice.call_args
        assert "2 个会话" in call_args.kwargs.get("title", "") or any("2 个会话" in str(arg) for arg in call_args.args)

    def test_session_display_format(self, mock_agent, sample_sessions):
        """测试会话显示格式"""
        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox") as mock_checkbox:
                with mock.patch("questionary.Choice") as mock_choice:
                    mock_choice.return_value = mock.MagicMock()
                    mock_checkbox.return_value.ask.return_value = sample_sessions
                    select_sessions_interactive(sample_sessions, mock_agent)

        # Verify Choice was created for each session
        assert mock_choice.call_count == len(sample_sessions)
