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
        mock_agent.scan.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", return_value="1"):
            result = select_agent_simple(agents)

        assert result == mock_agent

    def test_select_invalid_index(self, mock_agent, capsys):
        """测试选择无效索引"""
        mock_agent.scan.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", return_value="5"):
            result = select_agent_simple(agents)

        assert result is None

    def test_select_invalid_input(self, mock_agent, capsys):
        """测试无效输入"""
        mock_agent.scan.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", return_value="invalid"):
            result = select_agent_simple(agents)

        assert result is None

    def test_select_eof_error(self, mock_agent, capsys):
        """测试 EOF 错误处理"""
        mock_agent.scan.return_value = ["session1"]
        agents = [mock_agent]

        with mock.patch("builtins.input", side_effect=EOFError()):
            result = select_agent_simple(agents)

        assert result is None


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
