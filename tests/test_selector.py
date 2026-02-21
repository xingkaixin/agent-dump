"""
测试 selector.py 模块
"""

from unittest import mock

import questionary
import pytest

from agent_dump.selector import is_terminal, select_sessions_interactive, select_sessions_simple


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


class TestSelectSessionsSimple:
    """测试 select_sessions_simple 函数"""

    def test_select_all_sessions(self, sample_sessions, capsys):
        """测试选择所有会话"""
        with mock.patch("builtins.input", return_value="all"):
            result = select_sessions_simple(sample_sessions)

        assert len(result) == 2
        assert result[0]["id"] == "session-001"
        assert result[1]["id"] == "session-002"

    def test_select_specific_sessions(self, sample_sessions, capsys):
        """测试通过索引选择特定会话"""
        with mock.patch("builtins.input", return_value="1,2"):
            result = select_sessions_simple(sample_sessions)

        assert len(result) == 2
        assert result[0]["id"] == "session-001"
        assert result[1]["id"] == "session-002"

    def test_select_single_session(self, sample_sessions, capsys):
        """测试选择单个会话"""
        with mock.patch("builtins.input", return_value="2"):
            result = select_sessions_simple(sample_sessions)

        assert len(result) == 1
        assert result[0]["id"] == "session-002"

    def test_select_out_of_range(self, sample_sessions, capsys):
        """测试选择超出范围的索引"""
        with mock.patch("builtins.input", return_value="1,5,10"):
            result = select_sessions_simple(sample_sessions)

        # 只有第一个有效
        assert len(result) == 1
        assert result[0]["id"] == "session-001"

    def test_select_invalid_input(self, sample_sessions, capsys):
        """测试无效输入"""
        with mock.patch("builtins.input", return_value="invalid"):
            result = select_sessions_simple(sample_sessions)

        assert result == []

    def test_select_eof_error(self, sample_sessions, capsys):
        """测试 EOF 错误处理"""
        with mock.patch("builtins.input", side_effect=EOFError()):
            result = select_sessions_simple(sample_sessions)

        assert result == []

    def test_select_empty_sessions(self, capsys):
        """测试空会话列表"""
        with mock.patch("builtins.input", return_value=""):
            result = select_sessions_simple([])
        assert result == []


class TestSelectSessionsInteractive:
    """测试 select_sessions_interactive 函数"""

    def test_empty_sessions(self, capsys):
        """测试空会话列表"""
        result = select_sessions_interactive([])
        assert result == []
        captured = capsys.readouterr()
        assert "No sessions found" in captured.out

    def test_non_terminal_uses_simple_mode(self, sample_sessions):
        """测试非终端环境使用简单模式"""
        with mock.patch("agent_dump.selector.is_terminal", return_value=False):
            with mock.patch("agent_dump.selector.select_sessions_simple") as mock_simple:
                mock_simple.return_value = sample_sessions[:1]
                result = select_sessions_interactive(sample_sessions)

        mock_simple.assert_called_once_with(sample_sessions)
        assert result == sample_sessions[:1]

    def test_terminal_uses_questionary(self, sample_sessions):
        """测试终端环境使用 questionary"""
        # 创建一个 mock prompt 对象
        mock_prompt = mock.MagicMock()
        mock_prompt.ask.return_value = sample_sessions

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox", return_value=mock_prompt) as mock_checkbox:
                result = select_sessions_interactive(sample_sessions)

        mock_checkbox.assert_called_once()
        assert result == sample_sessions

    def test_questionary_returns_none(self, sample_sessions):
        """测试 questionary 返回 None 时"""
        # 创建一个 mock prompt 对象
        mock_prompt = mock.MagicMock()
        mock_prompt.ask.return_value = None

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox", return_value=mock_prompt):
                result = select_sessions_interactive(sample_sessions)

        assert result == []

    def test_long_title_truncation(self):
        """测试长标题截断"""
        sessions = [
            {
                "id": "test",
                "title": "A" * 100,  # 很长的标题
                "created_formatted": "2024-01-01 00:00:00",
            }
        ]

        with mock.patch("agent_dump.selector.is_terminal", return_value=True):
            with mock.patch("questionary.checkbox") as mock_checkbox:
                mock_checkbox.return_value.ask.return_value = sessions
                select_sessions_interactive(sessions)

        # 验证 questionary.Choice 被正确创建
        call_args = mock_checkbox.call_args
        assert call_args is not None
        choices = call_args[1].get("choices", [])
        # 第一个 choice 的 title 应该被截断
        if choices:
            assert len(choices[0].title) <= 65  # 60 + "..."
