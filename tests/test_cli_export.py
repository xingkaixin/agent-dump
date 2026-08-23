"""Interactive export format and output tests."""

from pathlib import Path
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
from agent_dump.command_plan import (
    ListOperation,
    SearchOperation,
)
from agent_dump.config import ExportConfig


class TestMain:
    @pytest.mark.parametrize(
        "argv",
        [
            ["agent-dump", "--list", "--format", "print"],
            ["agent-dump", "--search", "bug", "--format", "print"],
            ["agent-dump", "-d", "3", "--format", "print"],
            ["agent-dump", "-q", "bug", "--format", "print"],
        ],
    )
    def test_main_validates_explicit_and_implicit_list_formats_consistently(self, argv):
        with (
            mock.patch("agent_dump.cli.load_export_config", return_value=ExportConfig()),
            mock.patch("agent_dump.cli.handle_session_modes", return_value=0) as mock_handle,
            mock.patch("sys.argv", argv),
        ):
            result = main()

        assert result == 0
        operation = mock_handle.call_args.args[0]
        assert isinstance(operation, (ListOperation, SearchOperation))

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

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(Path("test.json"))

                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "--output", str(output_dir)]):
                        main()

            mock_export.assert_called_once()
            args = mock_export.call_args
            assert str(output_dir) in str(args[0][3])

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
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(Path("test.json"))

                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "-output", str(output_dir)]):
                        main()

            mock_export.assert_called_once()
            args = mock_export.call_args
            assert str(output_dir) in str(args[0][3])

    def test_main_uses_configured_output_for_interactive_json(self, tmp_path):
        configured_output = tmp_path / "configured-output"

        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch(
                "agent_dump.cli.load_export_config", return_value=ExportConfig(output=str(configured_output))
            ):
                with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                    with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                        mock_select.return_value = [mock.MagicMock()]
                        mock_export.return_value = make_export_result(configured_output / "opencode" / "test.json")

                        with mock.patch("sys.argv", ["agent-dump", "--interactive"]):
                            main()

            mock_export.assert_called_once()
            args = mock_export.call_args
            assert args.kwargs["output_base_dirs"]["json"] == configured_output
            assert args.args[3] == configured_output

    def test_main_interactive_markdown_ignores_configured_output(self, tmp_path):
        configured_output = tmp_path / "configured-output"

        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch(
                "agent_dump.cli.load_export_config", return_value=ExportConfig(output=str(configured_output))
            ):
                with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                    with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                        mock_select.return_value = [mock.MagicMock()]
                        mock_export.return_value = make_export_result(Path("test.md"))

                        with mock.patch("sys.argv", ["agent-dump", "--interactive", "--format", "markdown"]):
                            main()

            args = mock_export.call_args
            assert args.kwargs["output_base_dirs"]["markdown"] == Path("./sessions")
            assert args.args[3] == Path("./sessions")

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
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(Path("test.md"))

                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "--format", "md"]):
                        result = main()

        assert result == 0
        mock_export.assert_called_once()
        assert mock_export.call_args.args[2] == ["markdown"]

    def test_main_interactive_with_format_print_returns_1(self, capsys):
        """测试 --interactive + -format print 返回错误"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--interactive", "-format", "print"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "--interactive 模式不支持 print" in captured.out

    def test_main_interactive_with_multi_formats(self):
        """测试 --interactive 支持多格式导出"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(
                        Path("a.json"),
                        Path("a.md"),
                        Path("a.raw.json"),
                    )

                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "--format", "json,markdown,raw"]):
                        result = main()

        assert result == 0
        assert mock_export.call_args.args[2] == ["json", "markdown", "raw"]

    def test_main_interactive_with_format_json_print_returns_1(self, capsys):
        """测试 --interactive + 多格式包含 print 返回错误"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--interactive", "-format", "json,print"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "--interactive 模式不支持 print" in captured.out

    def test_main_interactive_with_raw_format(self):
        """测试 --interactive + raw 会传给统一导出入口"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.session_workflow.select_sessions_interactive") as mock_select:
                with mock.patch("agent_dump.session_workflow.export_sessions_for_formats") as mock_export:
                    mock_select.return_value = [mock.MagicMock()]
                    mock_export.return_value = make_export_result(Path("a.raw.json"))

                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "--format", "raw"]):
                        result = main()

        assert result == 0
        assert mock_export.call_args.args[2] == ["raw"]

    def test_main_invalid_format_list_exits(self, capsys):
        """测试无效格式列表会被 argparse 拒绝"""
        with mock.patch("sys.argv", ["agent-dump", "--interactive", "--format", "json,foo"]):
            with pytest.raises(SystemExit):
                main()

        captured = capsys.readouterr()
        assert "无效的格式列表" in captured.err

    def test_main_explicit_empty_format_exits(self, capsys):
        with mock.patch("sys.argv", ["agent-dump", "--list", "--format", ""]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2
        assert expect(LocaleKeys.CLI_FORMAT_INVALID, value="") in capsys.readouterr().err

    def test_main_list_mode_warns_and_continues_when_format_specified(self, capsys):
        """测试 --list + -format 会警告但继续"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
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
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list", "-output", str(tmp_path / "x")]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "--list 模式会忽略 -output/--output 参数" in captured.out
