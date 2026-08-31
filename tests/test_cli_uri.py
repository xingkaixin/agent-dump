"""URI CLI workflow tests."""

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from unittest import mock

from cli_test_support import (
    configure_scanner_sessions,
)
from locale_helpers import Keys as LocaleKeys, expect
import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.codex import CodexAgent
from agent_dump.cli import (
    main,
)
from agent_dump.config import AIConfig, AIConfigError, ExportConfig
from agent_dump.diagnostics import source_missing
from agent_dump.paths import SearchRoot
from agent_dump.scanner import AgentScanner


def _ai_config_document(config: object | None, *, source_exists: bool = True) -> mock.MagicMock:
    document = mock.MagicMock()
    document.ai_config.return_value = config
    document.source_exists = source_exists
    return document


class TestMain:
    def test_main_uri_mode_codex_threads_variant(self, capsys):
        """测试 URI 模式支持 codex://threads/<id> 变体"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": []
            }

            mock_session = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id") as mock_find:
                mock_find.return_value = (mock_agent, mock_session)

                with mock.patch(
                    "sys.argv",
                    ["agent-dump", "codex://threads/019c8d87-ecc4-7080-bde9-3e257c97cb99"],
                ):
                    result = main()

            assert result == 0
            mock_find.assert_called_once_with(
                mock_scanner,
                "019c8d87-ecc4-7080-bde9-3e257c97cb99",
                agent_name="codex",
            )

            captured = capsys.readouterr()
            assert "# Session Dump" in captured.out

    def test_main_uri_mode_invalid_uri(self, capsys):
        """测试 URI 模式下无效 URI 会报错"""
        with mock.patch("sys.argv", ["agent-dump", "invalid-uri"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "诊断信息" in captured.out
        assert "URI 格式无效" in captured.out
        assert "解析后的 URI: invalid-uri" in captured.out
        assert "下一步" in captured.out

    def test_main_uri_mode_uses_targeted_lookup_without_availability_scan(self, capsys):
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = {"messages": []}
            mock_session = mock.MagicMock()
            mock_session.id = "session-001"
            mock_scanner.agents = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch(
                "agent_dump.uri_workflow.find_session_by_id",
                return_value=(mock_agent, mock_session),
            ) as mock_find:
                with mock.patch("sys.argv", ["agent-dump", "codex://session-001"]):
                    result = main()

        assert result == 0
        mock_scanner.get_available_agents.assert_not_called()
        mock_find.assert_called_once_with(mock_scanner, "session-001", agent_name="codex")
        assert "# Session Dump" in capsys.readouterr().out

    def test_main_uri_mode_session_not_found(self, capsys, tmp_path):
        """测试 URI 模式下找不到会话"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = [mock.MagicMock()]
            configure_scanner_sessions(mock_scanner)
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "Codex"
            mock_agent.get_search_roots.return_value = (SearchRoot("CODEX_HOME/sessions", tmp_path / "codex"),)
            mock_scanner.agents = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=None):
                with mock.patch("sys.argv", ["agent-dump", "codex://session-001"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "未找到匹配的会话" in captured.out
        assert "解析后的 URI: codex://session-001" in captured.out
        assert "session_id: session-001" in captured.out
        assert "先运行 `agent-dump --list`" in captured.out

    def test_main_uri_mode_get_session_data_failed(self, capsys):
        """测试 URI 模式获取会话数据异常"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.side_effect = mock_agent.get_session_data.side_effect = RuntimeError(
                "read error"
            )
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id") as mock_find:
                mock_find.return_value = (mock_agent, mock.MagicMock())

                with mock.patch("sys.argv", ["agent-dump", "codex://session-001"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "读取会话数据失败" in captured.out
        assert "read error" in captured.out

    def test_main_uri_mode_head_success_does_not_load_full_session(self, capsys):
        """测试 URI + --head 仅输出摘要，不读取完整 session_data。"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_session_head.return_value = {
                "agent": "Codex",
                "title": "Test Session",
                "created_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
                "cwd_or_project": "/workspace/demo",
                "model": "gpt-5.4",
                "message_count": 12,
                "subtargets": ["worker-a", "worker-b"],
            }
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id") as mock_find:
                mock_find.return_value = (mock_agent, mock.MagicMock())

                with mock.patch("sys.argv", ["agent-dump", "codex://session-001", "--head"]):
                    result = main()

        assert result == 0
        mock_agent.get_cached_session_data.assert_not_called()
        captured = capsys.readouterr()
        assert "# Session Head" in captured.out
        assert "Message Count: 12" in captured.out

    def test_main_uri_mode_head_with_format_returns_1(self, capsys):
        """测试 URI + --head + --format 返回错误。"""
        with mock.patch("sys.argv", ["agent-dump", "codex://session-001", "--head", "--format", "json"]):
            result = main()

        assert result == 1
        assert "--head 不能与 -format/--format 同时使用" in capsys.readouterr().out

    def test_main_uri_mode_head_with_summary_returns_1(self, capsys):
        """测试 URI + --head + --summary 返回错误。"""
        with mock.patch("sys.argv", ["agent-dump", "codex://session-001", "--head", "--summary"]):
            result = main()

        assert result == 1
        assert "--head 不能与 --summary 同时使用" in capsys.readouterr().out

    def test_main_non_uri_mode_head_warns_and_continues(self, capsys):
        """测试非 URI 模式使用 --head 会警告并继续原有流程。"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = []
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list", "--head"]):
                result = main()

        # 本测试关心的是那句警告；退出码 1 来自「无可用 provider」（mock 返回空列表），
        # 与 --head 无关，见 AD-145 的退出码约定
        assert result == 1
        assert "--head 仅支持 URI 模式" in capsys.readouterr().out

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

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "sys.argv",
                    [
                        "agent-dump",
                        "codex://session-001",
                        "-format=json",
                        f"-output={output_root}",
                    ],
                ):
                    result = main()

        assert result == 0
        mock_agent.export_session.assert_called_once_with(mock_session, expected_output_dir)
        captured = capsys.readouterr()
        assert "# Session Dump" not in captured.out
        assert str(expected_output) in captured.out

    def test_main_uri_mode_json_uses_configured_output_when_unspecified(self, capsys, tmp_path):
        configured_output = tmp_path / "configured-out"
        expected_output = configured_output / "codex" / "session-001.json"

        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_session = mock.MagicMock()
            mock_session.id = "session-001"
            mock_agent.export_session.return_value = expected_output

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch(
                "agent_dump.cli.load_export_config", return_value=ExportConfig(output=str(configured_output))
            ):
                with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                    with mock.patch("sys.argv", ["agent-dump", "codex://session-001", "--format", "json"]):
                        result = main()

        assert result == 0
        mock_agent.export_session.assert_called_once_with(mock_session, configured_output / "codex")
        assert str(expected_output) in capsys.readouterr().out

    def test_main_uri_mode_markdown_ignores_configured_output_when_unspecified(self, capsys, tmp_path):
        configured_output = tmp_path / "configured-out"

        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}]
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch(
                "agent_dump.cli.load_export_config", return_value=ExportConfig(output=str(configured_output))
            ):
                with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                    with mock.patch("sys.argv", ["agent-dump", "codex://session-001", "--format", "markdown"]):
                        result = main()

        assert result == 0
        expected_output = Path("./sessions") / "codex" / "session-001.md"
        assert expected_output.exists()
        assert str(expected_output) in capsys.readouterr().out
        expected_output.unlink()

    @pytest.mark.parametrize(
        "output_args",
        [
            ("--output", "{output}"),
            ("--out", "{output}"),
            ("--output={output}",),
            ("--out={output}",),
        ],
    )
    def test_main_uri_mode_json_creates_missing_output_dir(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path, output_args: tuple[str, ...]
    ) -> None:
        """测试 URI + --format json 在输出目录不存在时也能导出"""
        from agent_dump.agents.claudecode import ClaudeCodeAgent

        agent = ClaudeCodeAgent()
        session_file = tmp_path / "test-uri.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "user",
                    "uuid": "msg-001",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": {"role": "user", "content": "Hello Claude"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        session = Session(
            id="session-001",
            title="Test Session",
            created_at=datetime(2026, 1, 1, 12, 0, 0),
            updated_at=datetime(2026, 1, 1, 12, 0, 0),
            source_path=session_file,
            metadata={"cwd": "/test", "version": "1.0"},
        )

        output_root = tmp_path / "missing-root"
        configured_output = tmp_path / "configured-out"
        expected_output = output_root / "claudecode" / "session-001.json"

        with (
            mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class,
            mock.patch("agent_dump.cli.load_export_config", return_value=ExportConfig(output=str(configured_output))),
        ):
            mock_scanner = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = [agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with (
                mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(agent, session)),
                mock.patch(
                    "sys.argv",
                    [
                        "agent-dump",
                        "claude://session-001",
                        "--format",
                        "json",
                        *(arg.format(output=output_root) for arg in output_args),
                    ],
                ),
            ):
                result = main()

        assert result == 0
        assert expected_output.exists()
        assert not configured_output.exists()
        captured = capsys.readouterr()
        assert str(expected_output) in captured.out

    def test_main_uri_mode_md_writes_file_and_not_print_body(self, capsys, tmp_path):
        """测试 URI + -format md 写文件且不输出正文"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}]
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.md"

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
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

    def test_main_uri_mode_print_and_json(self, capsys, tmp_path):
        """测试 URI + print,json 会先打印再写文件"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}]
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output_dir = output_root / "codex"
            expected_output = expected_output_dir / "session-001.json"
            mock_agent.export_session_with_fields.return_value = expected_output

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "sys.argv",
                    ["agent-dump", "codex://session-001", "--format", "print,json", "--output", str(output_root)],
                ):
                    result = main()

        assert result == 0
        mock_agent.export_session.assert_not_called()
        mock_agent.export_session_with_fields.assert_called_once_with(
            mock_session,
            expected_output_dir,
            None,
            session_data=mock_agent.get_cached_session_data.return_value,
        )
        captured = capsys.readouterr()
        assert "# Session Dump" in captured.out
        assert str(expected_output) in captured.out

    def test_main_uri_mode_print_json_raw(self, capsys, tmp_path):
        """测试 URI + print,json,raw 会打印并导出两个文件"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": []
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output_dir = output_root / "codex"
            json_output = expected_output_dir / "session-001.json"
            raw_output = expected_output_dir / "session-001.raw.jsonl"
            mock_agent.export_session_with_fields.return_value = json_output
            mock_agent.export_raw_session.return_value = raw_output

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "sys.argv",
                    [
                        "agent-dump",
                        "codex://session-001",
                        "--format",
                        "print,json,raw",
                        "--output",
                        str(output_root),
                    ],
                ):
                    result = main()

        assert result == 0
        mock_agent.export_session.assert_not_called()
        mock_agent.export_session_with_fields.assert_called_once_with(
            mock_session,
            expected_output_dir,
            None,
            session_data=mock_agent.get_cached_session_data.return_value,
        )
        mock_agent.export_raw_session.assert_called_once_with(mock_session, expected_output_dir)
        captured = capsys.readouterr()
        assert "# Session Dump" in captured.out
        assert str(json_output) in captured.out
        assert str(raw_output) in captured.out

    def test_main_uri_mode_cursor_rejects_raw(self, capsys):
        """测试 Cursor URI 模式拒绝 raw 格式"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "cursor"
            mock_agent.display_name = "Cursor"
            mock_agent.unsupported_uri_formats = frozenset({"raw", "markdown"})
            mock_session = mock.MagicMock()
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch("sys.argv", ["agent-dump", "cursor://request-001", "--format", "raw"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "缺失能力" in captured.out
        assert (
            expect(LocaleKeys.DIAG_URI_CAPABILITY_DETAIL, agent="Cursor", supported="json, print", requested="raw")
            in captured.out
        )

    def test_main_uri_mode_cursor_json_print_success(self, capsys, tmp_path):
        """测试 Cursor URI 支持 json,print"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "cursor"
            mock_agent.display_name = "Cursor"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hi"}]}]
            }
            mock_session = mock.MagicMock()
            mock_session.id = "request-001"
            expected_output = tmp_path / "out" / "cursor" / "request-001.json"
            mock_agent.export_session_with_fields.return_value = expected_output
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "sys.argv",
                    [
                        "agent-dump",
                        "cursor://request-001",
                        "--format",
                        "json,print",
                        "--output",
                        str(tmp_path / "out"),
                    ],
                ):
                    result = main()

        assert result == 0
        mock_agent.export_session_with_fields.assert_called_once_with(
            mock_session,
            expected_output.parent,
            None,
            session_data=mock_agent.get_cached_session_data.return_value,
        )
        captured = capsys.readouterr()
        assert "# Session Dump" in captured.out
        assert str(expected_output) in captured.out

    def test_main_uri_mode_raw_source_missing_shows_diagnostic(self, capsys, tmp_path):
        """测试原始文件缺失时输出 searched roots 和下一步。"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_session = mock.MagicMock()
            mock_session.id = "session-001"
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner.agents = [mock_agent]
            mock_scanner_class.return_value = mock_scanner

            mock_agent.export_raw_session.side_effect = source_missing(
                "raw session source is missing",
                missing_path=tmp_path / "missing.jsonl",
                searched_roots=(f"Codex: CODEX_HOME/sessions: {tmp_path / 'codex'}",),
                next_steps=("重新运行 `agent-dump --list` 检查该会话是否仍可见。",),
            )

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch("sys.argv", ["agent-dump", "codex://session-001", "--format", "raw"]):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "raw session source is missing" in captured.out
        assert f"missing path: {tmp_path / 'missing.jsonl'}" in captured.out
        assert expect(LocaleKeys.DIAGNOSTIC_SEARCHED_ROOTS) in captured.out

    def test_main_uri_mode_json_with_summary_success(self, capsys, tmp_path):
        """测试 URI + json + --summary 成功写入 summary 字段"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "id": "session-001",
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Snapshot body"}]}],
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.json"

            def _export_json(
                session: Session,
                output_dir: Path,
                fields: Mapping[str, Any] | None,
                *,
                session_data: Mapping[str, Any],
            ) -> Path:
                output_dir.mkdir(parents=True, exist_ok=True)
                expected_output.write_text(
                    json.dumps({**session_data, **(fields or {})}),
                    encoding="utf-8",
                )
                return expected_output

            mock_agent.export_session_with_fields.side_effect = _export_json
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "agent_dump.uri_workflow.load_projectable_config_document",
                    return_value=_ai_config_document(mock.MagicMock()),
                ):
                    with mock.patch("agent_dump.uri_workflow.validate_ai_config", return_value=(True, [])):
                        with mock.patch("agent_dump.cli.request_summary_from_llm", return_value="# summary markdown"):
                            with mock.patch(
                                "sys.argv",
                                [
                                    "agent-dump",
                                    "codex://session-001",
                                    "--format",
                                    "json",
                                    "--summary",
                                    "--output",
                                    str(output_root),
                                ],
                            ):
                                result = main()

        assert result == 0
        exported = json.loads(expected_output.read_text(encoding="utf-8"))
        assert exported == {**mock_agent.get_cached_session_data.return_value, "summary": "# summary markdown"}
        mock_agent.export_session_with_fields.assert_called_once_with(
            mock_session,
            expected_output.parent,
            {"summary": "# summary markdown"},
            session_data=mock_agent.get_cached_session_data.return_value,
        )
        captured = capsys.readouterr()
        assert "正在调用 AI 生成会话总结，请稍候" in captured.err
        assert "已将 summary 写入 JSON" in captured.out

    def test_main_uri_mode_print_json_with_summary_success(self, capsys, tmp_path):
        """测试 URI + print,json + --summary 同时打印正文并写入 summary"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}]
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.json"

            def _export_json(
                session: Session,
                output_dir: Path,
                fields: Mapping[str, Any] | None,
                *,
                session_data: Mapping[str, Any],
            ) -> Path:
                output_dir.mkdir(parents=True, exist_ok=True)
                expected_output.write_text(
                    json.dumps({**session_data, **(fields or {})}),
                    encoding="utf-8",
                )
                return expected_output

            mock_agent.export_session_with_fields.side_effect = _export_json
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "agent_dump.uri_workflow.load_projectable_config_document",
                    return_value=_ai_config_document(mock.MagicMock()),
                ):
                    with mock.patch("agent_dump.uri_workflow.validate_ai_config", return_value=(True, [])):
                        with mock.patch("agent_dump.cli.request_summary_from_llm", return_value="# summary markdown"):
                            with mock.patch(
                                "sys.argv",
                                [
                                    "agent-dump",
                                    "codex://session-001",
                                    "--format",
                                    "print,json",
                                    "--summary",
                                    "--output",
                                    str(output_root),
                                ],
                            ):
                                result = main()

        assert result == 0
        exported = json.loads(expected_output.read_text(encoding="utf-8"))
        assert exported == {**mock_agent.get_cached_session_data.return_value, "summary": "# summary markdown"}
        mock_agent.export_session_with_fields.assert_called_once_with(
            mock_session,
            expected_output.parent,
            {"summary": "# summary markdown"},
            session_data=mock_agent.get_cached_session_data.return_value,
        )
        captured = capsys.readouterr()
        assert "# Session Dump" in captured.out
        assert str(expected_output) in captured.out

    def test_main_uri_summary_keeps_snapshot_when_source_changes(
        self, codex_session_tree: dict[str, Any], tmp_path: Path
    ) -> None:
        session_id = codex_session_tree["session_id"]
        source_file = codex_session_tree["session_file"]
        original_source = source_file.read_text(encoding="utf-8")
        new_message = "NEW_AFTER_SUMMARY_SNAPSHOT"
        agent = CodexAgent()
        output_root = tmp_path / "out"
        config = AIConfig(provider="openai", base_url="https://example.invalid/v1", model="test", api_key="test")

        def summarize(config: AIConfig, prompt: str) -> str:
            assert config.model == "test"
            assert codex_session_tree["user_text"] in prompt
            assert codex_session_tree["assistant_text"] in prompt
            assert new_message not in prompt
            source_file.write_text(
                original_source
                + json.dumps(
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-20T10:06:00Z",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": new_message}],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return "# snapshot summary"

        with (
            mock.patch("agent_dump.cli.AgentScanner", return_value=AgentScanner([agent])),
            mock.patch(
                "agent_dump.uri_workflow.load_projectable_config_document", return_value=_ai_config_document(config)
            ),
            mock.patch("agent_dump.cli.request_summary_from_llm", side_effect=summarize) as request_summary,
            mock.patch(
                "sys.argv",
                [
                    "agent-dump",
                    f"codex://{session_id}",
                    "--summary",
                    "--format",
                    "json,markdown,raw",
                    "--output",
                    str(output_root),
                ],
            ),
        ):
            result = main()

        assert result == 0
        request_summary.assert_called_once()
        output_dir = output_root / "codex"
        exported = json.loads((output_dir / f"{session_id}.json").read_text(encoding="utf-8"))
        exported_messages = json.dumps(exported["messages"], ensure_ascii=False)
        assert exported["summary"] == "# snapshot summary"
        assert codex_session_tree["user_text"] in exported_messages
        assert codex_session_tree["assistant_text"] in exported_messages
        assert new_message not in exported_messages
        markdown = (output_dir / f"{session_id}.md").read_text(encoding="utf-8")
        assert codex_session_tree["user_text"] in markdown
        assert new_message not in markdown
        assert (output_dir / f"{session_id}.raw.jsonl").read_bytes() == source_file.read_bytes()
        session = agent.find_session_by_id(session_id)
        assert session is not None
        assert new_message in json.dumps(agent.get_cached_session_data(session), ensure_ascii=False)

    def test_main_uri_mode_summary_without_json_warns_and_skips(self, capsys, tmp_path):
        """测试 URI + --summary 但 format 不含 json 时警告并跳过"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}]
            }

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"
            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.md"

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "sys.argv",
                    [
                        "agent-dump",
                        "codex://session-001",
                        "--format",
                        "markdown",
                        "--summary",
                        "--output",
                        str(output_root),
                    ],
                ):
                    result = main()

        assert result == 0
        assert expected_output.exists()
        captured = capsys.readouterr()
        assert "--summary 需要 --format 中包含 json" in captured.out

    def test_main_uri_mode_summary_with_missing_config_warns_and_exports_json(self, capsys, tmp_path):
        """测试 URI + --summary 缺失配置时仅警告，JSON 正常导出且无 summary"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.json"

            def _export_json(session, output_dir):
                output_dir.mkdir(parents=True, exist_ok=True)
                expected_output.write_text(json.dumps({"id": "session-001", "messages": []}), encoding="utf-8")
                return expected_output

            mock_agent.export_session.side_effect = _export_json
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "agent_dump.uri_workflow.load_projectable_config_document",
                    return_value=_ai_config_document(None, source_exists=False),
                ):
                    with mock.patch(
                        "agent_dump.uri_workflow.validate_ai_config",
                        return_value=(False, [AIConfigError.MISSING_FILE]),
                    ):
                        with mock.patch(
                            "sys.argv",
                            [
                                "agent-dump",
                                "codex://session-001",
                                "--format",
                                "json",
                                "--summary",
                                "--output",
                                str(output_root),
                            ],
                        ):
                            result = main()

        assert result == 0
        exported = json.loads(expected_output.read_text(encoding="utf-8"))
        assert "summary" not in exported
        captured = capsys.readouterr()
        assert "未找到配置文件" in captured.out

    def test_main_uri_mode_summary_with_incomplete_config_warns_and_exports_json(self, capsys, tmp_path):
        """测试 URI + --summary 配置缺字段时仅警告，JSON 正常导出且无 summary"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.json"

            def _export_json(session, output_dir):
                output_dir.mkdir(parents=True, exist_ok=True)
                expected_output.write_text(json.dumps({"id": "session-001", "messages": []}), encoding="utf-8")
                return expected_output

            mock_agent.export_session.side_effect = _export_json
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "agent_dump.uri_workflow.load_projectable_config_document",
                    return_value=_ai_config_document(mock.MagicMock()),
                ):
                    with mock.patch(
                        "agent_dump.uri_workflow.validate_ai_config",
                        return_value=(False, [AIConfigError.MODEL, AIConfigError.API_KEY]),
                    ):
                        with mock.patch(
                            "sys.argv",
                            [
                                "agent-dump",
                                "codex://session-001",
                                "--format",
                                "json",
                                "--summary",
                                "--output",
                                str(output_root),
                            ],
                        ):
                            result = main()

        assert result == 0
        exported = json.loads(expected_output.read_text(encoding="utf-8"))
        assert "summary" not in exported
        captured = capsys.readouterr()
        assert "配置缺少字段: model,api_key" in captured.out

    def test_main_uri_mode_summary_api_error_warns_and_exports_json(self, capsys, tmp_path):
        """测试 URI + --summary 请求失败时仅警告，JSON 正常导出且无 summary"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_cached_session_data.return_value = mock_agent.get_session_data.return_value = {
                "id": "session-001",
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Snapshot body"}]}],
            }
            mock_session = mock.MagicMock()
            mock_session.id = "session-001"

            output_root = tmp_path / "out"
            expected_output = output_root / "codex" / "session-001.json"

            def _export_json(
                session: Session,
                output_dir: Path,
                fields: Mapping[str, Any] | None,
                *,
                session_data: Mapping[str, Any],
            ) -> Path:
                output_dir.mkdir(parents=True, exist_ok=True)
                expected_output.write_text(json.dumps({**session_data, **(fields or {})}), encoding="utf-8")
                return expected_output

            mock_agent.export_session_with_fields.side_effect = _export_json
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "agent_dump.uri_workflow.load_projectable_config_document",
                    return_value=_ai_config_document(mock.MagicMock()),
                ):
                    with mock.patch("agent_dump.uri_workflow.validate_ai_config", return_value=(True, [])):
                        with mock.patch("agent_dump.cli.request_summary_from_llm", side_effect=RuntimeError("boom")):
                            with mock.patch(
                                "sys.argv",
                                [
                                    "agent-dump",
                                    "codex://session-001",
                                    "--format",
                                    "json",
                                    "--summary",
                                    "--output",
                                    str(output_root),
                                ],
                            ):
                                result = main()

        assert result == 0
        exported = json.loads(expected_output.read_text(encoding="utf-8"))
        assert exported == mock_agent.get_cached_session_data.return_value
        mock_agent.export_session_with_fields.assert_called_once_with(
            mock_session,
            expected_output.parent,
            None,
            session_data=mock_agent.get_cached_session_data.return_value,
        )
        captured = capsys.readouterr()
        assert "正在调用 AI 生成会话总结，请稍候" in captured.err
        assert "AI 总结请求失败: boom" in captured.out

    def test_main_uri_mode_summary_preparation_failure_still_exports_raw(self, capsys, tmp_path):
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            read_error = OSError("transcript unreadable")
            mock_agent.get_cached_session_data.side_effect = read_error
            mock_agent.export_session.side_effect = read_error

            mock_session = mock.MagicMock()
            mock_session.id = "session-001"
            output_root = tmp_path / "out"
            raw_output = output_root / "codex" / "session-001.raw.jsonl"
            mock_agent.export_raw_session.return_value = raw_output
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.uri_workflow.find_session_by_id", return_value=(mock_agent, mock_session)):
                with mock.patch(
                    "agent_dump.uri_workflow.load_projectable_config_document",
                    return_value=_ai_config_document(mock.MagicMock()),
                ):
                    with mock.patch("agent_dump.uri_workflow.validate_ai_config", return_value=(True, [])):
                        with mock.patch("agent_dump.cli.request_summary_from_llm") as request_summary:
                            with mock.patch(
                                "sys.argv",
                                [
                                    "agent-dump",
                                    "codex://session-001",
                                    "--format",
                                    "json,raw",
                                    "--summary",
                                    "--output",
                                    str(output_root),
                                ],
                            ):
                                result = main()

        assert result == 0
        request_summary.assert_not_called()
        mock_agent.export_session.assert_called_once()
        mock_agent.export_raw_session.assert_called_once_with(mock_session, output_root / "codex")
        captured = capsys.readouterr()
        assert (
            expect(
                LocaleKeys.URI_SUMMARY_PREPARATION_FAILED_WARNING,
                error="transcript unreadable",
            )
            in captured.out
        )
        assert str(raw_output) in captured.out

    def test_main_non_uri_mode_summary_warns_and_continues(self, capsys):
        """测试非 URI 模式使用 --summary 时警告并继续原流程"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            mock_agent = mock.MagicMock()
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []
            mock_scanner.agents = [mock_agent]
            mock_scanner.get_available_agents.return_value = [mock_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "--list", "--summary"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "--summary 仅支持 URI 模式" in captured.out
