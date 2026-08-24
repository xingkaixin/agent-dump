"""Core CLI parsing and dispatch tests."""

from pathlib import Path
from unittest import mock

from locale_helpers import Keys as LocaleKeys, expect
import pytest

from agent_dump.__about__ import __version__
from agent_dump.cli import (
    main,
)


class TestMain:
    def test_main_configures_standard_stream_encoding(self):
        with (
            mock.patch("agent_dump.cli.configure_standard_stream_encoding") as mock_configure,
            mock.patch("agent_dump.cli._run", return_value=0),
        ):
            result = main()

        assert result == 0
        mock_configure.assert_called_once()

    def test_main_short_version_prints_and_exits(self, capsys):
        with mock.patch("sys.argv", ["agent-dump", "-v"]), pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == f"agent-dump {__version__}"

    def test_main_long_version_prints_and_exits(self, capsys):
        with mock.patch("sys.argv", ["agent-dump", "--version"]), pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == f"agent-dump {__version__}"

    def test_main_help_includes_version_option(self, capsys):
        with mock.patch("sys.argv", ["agent-dump", "--lang", "zh", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "-v, --version" in captured.out
        assert "显示版本号并退出" in captured.out

    def test_main_dispatches_config_mode(self):
        with mock.patch("agent_dump.cli.handle_config_command", return_value=0) as mock_handle:
            with mock.patch("sys.argv", ["agent-dump", "--config", "view"]):
                result = main()

        assert result == 0
        mock_handle.assert_called_once_with("view")

    @pytest.mark.parametrize("option", ["--providers", "--capabilities"])
    def test_main_dispatches_providers_mode(self, option: str) -> None:
        with mock.patch("agent_dump.cli.handle_providers_mode", return_value=0) as mock_handle:
            with mock.patch("sys.argv", ["agent-dump", option]):
                result = main()

        assert result == 0
        mock_handle.assert_called_once_with()

    def test_main_warns_when_mode_priority_ignores_an_option(self, capsys) -> None:
        with mock.patch("agent_dump.cli.handle_providers_mode", return_value=0):
            with mock.patch("sys.argv", ["agent-dump", "--providers", "--stats"]):
                result = main()

        assert result == 0
        assert expect(LocaleKeys.CLI_MODE_OPTIONS_IGNORED_WARNING, options="--stats") in capsys.readouterr().out

    def test_main_providers_shows_registered_capabilities_without_scanning(
        self,
        capsys,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(Path, "exists", lambda _path: False)
        monkeypatch.setattr("agent_dump.agents.zcode.sys.platform", "linux")

        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner:
            with mock.patch("sys.argv", ["agent-dump", "--providers"]):
                result = main()

        assert result == 0
        mock_scanner.assert_not_called()
        output = capsys.readouterr().out
        for provider in ("OpenCode", "ZCode", "Codex", "Kimi", "Claude Code", "Cursor", "Pi"):
            assert provider in output
        assert "Cursor | cursor:// | json, print | 已找到 0/1 | markdown, raw" in output
        assert "OpenCode | opencode:// | json, markdown, print, raw | 已找到 0/2" in output
        assert "ZCode:" in output
        assert "当前平台无默认路径" in output

    def test_main_keyboard_interrupt(self, capsys):
        """测试键盘中断处理"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_sessions.side_effect = KeyboardInterrupt()
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

    def test_main_dispatches_stats_mode(self, capsys):
        with mock.patch("agent_dump.cli.handle_stats_mode", return_value=0) as mock_handle:
            with mock.patch("sys.argv", ["agent-dump", "--stats"]):
                result = main()

        assert result == 0
        mock_handle.assert_called_once()
