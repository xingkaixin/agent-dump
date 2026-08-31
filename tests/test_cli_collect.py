"""Collect CLI workflow tests."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest import mock

from cli_test_support import (
    collect_operation_from,
    configure_scanner_sessions,
    configure_session_data_lease,
    make_config_document,
    make_session,
)
from locale_helpers import Keys, expect_contains
import pytest

from agent_dump.cli import (
    handle_collect_mode,
    main,
)
from agent_dump.collect_dates import CollectDateError, CollectDateErrorCode
from agent_dump.collect_models import (
    CollectOverviewProgress,
    CollectProgressEvent,
    CollectStartProgress,
    MergeSessionsProgress,
    PlanChunksProgress,
    RenderFinalProgress,
    ScanSessionsProgress,
    SummarizeChunksProgress,
    TreeReductionProgress,
    WriteOutputProgress,
)
from agent_dump.collect_prompts import FINAL_PROMPT_CHAR_BUDGET
from agent_dump.collect_workflow import resolve_collect_save_path, show_collect_progress
from agent_dump.command_plan import (
    CollectOperation,
)
from agent_dump.config import CollectConfig
from agent_dump.text_safety import has_unsafe_line_characters


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize(
    ("settings", "invalid_field"),
    [
        ('[collect]\nsummary_concurrency = 4oops\n[agent.codex]\ndeny = ["/private, work"]\n', "TOML"),
        ('[agent.codex]\ndeny = "/private"\n', "agent.codex.deny"),
        ('[agent.codex]\ndeny = ["/private", 42]\n', "agent.codex.deny"),
        ('[[agent.codex]]\ndeny = ["/private"]\n', "agent.codex"),
        ('[agent.codex.deny]\npaths = ["/private"]\n', "agent.codex.deny"),
        ('[[agent]]\ncodex = {deny = ["/private"]}\n', "agent"),
    ],
)
def test_collect_rejects_unsafe_config_before_discovery_or_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dry_run: bool,
    settings: str,
    invalid_field: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[ai]\nprovider = "openai"\nbase_url = "https://example.invalid/v1"\n'
        'model = "test"\napi_key = "test"\n' + settings,
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: config_path)
    argv = ["agent-dump", "--collect", *(["--dry-run"] if dry_run else [])]
    with (
        mock.patch("sys.argv", argv),
        mock.patch("agent_dump.cli.AgentScanner") as scanner,
        mock.patch("agent_dump.collect_requests.request_structured_summary_payload_from_llm") as chunk_request,
        mock.patch("agent_dump.cli.request_summary_from_llm") as final_request,
    ):
        assert main() == 1

    scanner.assert_not_called()
    chunk_request.assert_not_called()
    final_request.assert_not_called()
    assert expect_contains(capsys.readouterr().out, Keys.COLLECT_CONFIG_UNSAFE, field=invalid_field)


def test_collect_rejects_oversized_final_input_before_request(
    codex_session_tree: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[ai]\nprovider="openai"\nbase_url="https://example.invalid"\nmodel="test"\napi_key="test"\n'
        "[logging]\nenabled=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: config_path)
    monkeypatch.setattr("sys.argv", ["agent-dump", "--collect", "-since", "20260720", "-until", "20260720"])

    with (
        mock.patch(
            "agent_dump.collect_requests.request_structured_summary_payload_from_llm",
            return_value=json.dumps({"topics": ["x" * FINAL_PROMPT_CHAR_BUDGET]}),
        ) as chunk_request,
        mock.patch("agent_dump.cli.request_summary_from_llm") as final_request,
    ):
        result = main()

    assert result == 1
    chunk_request.assert_called()
    final_request.assert_not_called()
    assert expect_contains(capsys.readouterr().out, Keys.COLLECT_FINAL_INPUT_TOO_LARGE, limit=FINAL_PROMPT_CHAR_BUDGET)


class TestMain:
    def test_collect_handler_injects_all_llm_requesters(self) -> None:
        operation = collect_operation_from(argparse.Namespace())
        with (
            mock.patch("agent_dump.cli._handle_collect_mode", return_value=0) as workflow,
            mock.patch("agent_dump.cli.AgentScanner") as scanner_factory,
            mock.patch("agent_dump.cli.request_summary_from_llm") as final_requester,
            mock.patch("agent_dump.cli.request_structured_summary_from_llm") as structured_requester,
        ):
            assert handle_collect_mode(operation) == 0

        workflow.assert_called_once_with(
            operation,
            scanner_factory=scanner_factory,
            request_summary=final_requester,
            request_structured_summary=structured_requester,
        )

    def test_main_dispatches_collect_mode(self):
        with mock.patch("agent_dump.cli.handle_collect_mode", return_value=0) as mock_handle:
            with mock.patch("sys.argv", ["agent-dump", "--collect"]):
                result = main()

        assert result == 0
        mock_handle.assert_called_once()
        assert mock_handle.call_args.args[0].days is None

    def test_main_dispatches_collect_days(self) -> None:
        with mock.patch("agent_dump.cli.handle_collect_mode", return_value=0) as mock_handle:
            with mock.patch("sys.argv", ["agent-dump", "--collect", "-days", "30"]):
                result = main()

        assert result == 0
        assert mock_handle.call_args.args[0].days == 30

    def test_main_dispatches_collect_dry_run(self):
        with mock.patch("agent_dump.cli.handle_collect_mode", return_value=0) as mock_handle:
            with mock.patch("sys.argv", ["agent-dump", "--collect", "--dry-run"]):
                result = main()

        assert result == 0
        operation = mock_handle.call_args.args[0]
        assert isinstance(operation, CollectOperation)
        assert operation.dry_run is True

    def test_collect_mode_conflict(self, capsys):
        with mock.patch("sys.argv", ["agent-dump", "codex://session-001", "--collect"]):
            result = main()

        assert result == 1
        assert "--collect 不能与 URI/--interactive/--list 同时使用" in capsys.readouterr().out

    def test_collect_mode_passes_days_to_date_range(self) -> None:
        args = argparse.Namespace(
            collect=True,
            uri=None,
            interactive=False,
            list=False,
            days=30,
            since=None,
            until=None,
            save=None,
        )

        with mock.patch(
            "agent_dump.collect_workflow.resolve_collect_date_range",
            side_effect=CollectDateError(CollectDateErrorCode.INVALID_FORMAT, "invalid date"),
        ) as mock_resolve:
            result = handle_collect_mode(collect_operation_from(args))

        assert result == 1
        mock_resolve.assert_called_once_with(None, None, days=30)

    def test_collect_mode_accepts_agents_query_uri(self, tmp_path):
        args = argparse.Namespace(
            collect=True,
            uri="agents://.?q=bug&providers=codex&roles=user&limit=2",
            interactive=False,
            list=False,
            since=None,
            until=None,
            save=None,
        )
        mock_config = mock.MagicMock()
        mock_entry = mock.MagicMock()
        mock_planned_entry = mock.MagicMock()
        mock_entry.agent_display_name = "Codex"
        mock_planned_entry.chunks = (mock.MagicMock(),)
        mock_logger = mock.MagicMock()
        config_document = make_config_document(
            ai_config=mock_config,
            collect_config=mock.MagicMock(summary_concurrency=1, summary_timeout_seconds=30),
        )

        with mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document):
            with mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=mock_logger):
                with mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])):
                    with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
                        mock_scanner = mock.MagicMock()
                        known_agent = mock.MagicMock()
                        known_agent.name = "codex"
                        available_agent = mock.MagicMock()
                        available_agent.name = "codex"
                        mock_scanner.agents = [known_agent]
                        mock_scanner.get_available_agents.return_value = [available_agent]
                        configure_scanner_sessions(mock_scanner)
                        mock_scanner_class.return_value = mock_scanner
                        with mock.patch(
                            "agent_dump.collect_workflow.collect_entries", return_value=[mock_entry]
                        ) as mock_collect:
                            with mock.patch(
                                "agent_dump.collect_workflow.plan_collect_entries",
                                return_value=([mock_planned_entry], 1),
                            ):
                                with mock.patch(
                                    "agent_dump.collect_workflow.summarize_collect_entries",
                                    return_value=[mock.MagicMock()],
                                ):
                                    with mock.patch(
                                        "agent_dump.collect_workflow.reduce_collect_summaries",
                                        return_value=mock.MagicMock(),
                                    ):
                                        with mock.patch(
                                            "agent_dump.collect_workflow.build_collect_final_prompt",
                                            return_value="prompt",
                                        ):
                                            with mock.patch(
                                                "agent_dump.cli.request_summary_from_llm",
                                                return_value="# collect",
                                            ):
                                                with mock.patch(
                                                    "agent_dump.collect_workflow.write_collect_markdown",
                                                    return_value=tmp_path / "collect.md",
                                                ):
                                                    result = handle_collect_mode(collect_operation_from(args))

        assert result == 0
        query_spec = mock_collect.call_args.kwargs["query_spec"]
        assert query_spec.keyword == "bug"
        assert query_spec.agent_names == {"codex"}
        assert query_spec.roles == {"user"}
        assert query_spec.limit == 2
        assert query_spec.project_path == Path.cwd().resolve()

    def test_collect_mode_dry_run_skips_ai_config_llm_and_write(self, capsys, tmp_path):
        args = argparse.Namespace(
            collect=True,
            uri=None,
            interactive=False,
            list=False,
            since="2026-03-01",
            until="2026-03-05",
            save=str(tmp_path / "reports"),
            dry_run=True,
        )
        mock_entry = mock.MagicMock()
        mock_entry.agent_display_name = "Codex"
        mock_planned_entry = mock.MagicMock()
        mock_planned_entry.chunks = (mock.MagicMock(), mock.MagicMock())
        collect_config = CollectConfig(summary_concurrency=3)

        mock_scanner = mock.MagicMock()
        known_agent = mock.MagicMock()
        known_agent.name = "codex"
        available_agent = mock.MagicMock()
        available_agent.name = "codex"
        mock_scanner.agents = [known_agent]
        mock_scanner.get_available_agents.return_value = [available_agent]
        configure_scanner_sessions(mock_scanner)
        config_document = make_config_document(collect_config=collect_config)

        with (
            mock.patch(
                "agent_dump.collect_workflow.load_config_document",
                return_value=config_document,
            ) as mock_load_document,
            mock.patch("agent_dump.collect_workflow.validate_ai_config") as mock_validate_ai,
            mock.patch("agent_dump.collect_workflow.create_collect_logger") as mock_create_logger,
            mock.patch("agent_dump.cli.AgentScanner", return_value=mock_scanner),
            mock.patch("agent_dump.collect_workflow.collect_entries", return_value=[mock_entry]),
            mock.patch("agent_dump.collect_workflow.plan_collect_entries", return_value=([mock_planned_entry], 2)),
            mock.patch("agent_dump.collect_workflow.summarize_collect_entries") as mock_summarize,
            mock.patch("agent_dump.cli.request_summary_from_llm") as mock_request_summary,
            mock.patch("agent_dump.collect_workflow.write_collect_markdown") as mock_write,
        ):
            result = handle_collect_mode(collect_operation_from(args))

        assert result == 0
        mock_load_document.assert_called_once_with()
        config_document.ai_config.assert_not_called()
        config_document.collect_config.assert_called_once_with()
        config_document.logging_config.assert_not_called()
        mock_validate_ai.assert_not_called()
        mock_create_logger.assert_not_called()
        mock_summarize.assert_not_called()
        mock_request_summary.assert_not_called()
        mock_write.assert_not_called()
        output = capsys.readouterr().out
        assert "Collect dry-run 预览" in output
        assert "日期范围：2026-03-01 ~ 2026-03-05" in output
        assert "Provider 分布：Codex 1" in output
        assert "Session 数：1" in output
        assert "Chunk 数：2" in output
        assert "并发配置：3" in output
        assert str(tmp_path / "reports" / "agent-dump-collect-20260301-20260305.md") in output

    def test_collect_mode_dry_run_applies_agents_uri_path_scope_and_agent_denies(self, capsys, tmp_path):
        cwd = Path.cwd().resolve()
        output_path = tmp_path / "collect.md"
        args = argparse.Namespace(
            collect=True,
            uri="agents://.?providers=codex,claude",
            interactive=False,
            list=False,
            since="2026-03-01",
            until="2026-03-05",
            save=str(output_path),
            dry_run=True,
        )

        in_scope = make_session(
            "codex-in-scope",
            "Codex in scope",
            created_at=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
            metadata={"cwd": str(cwd / "app")},
        )
        out_of_scope = make_session(
            "codex-out-of-scope",
            "Codex out of scope",
            created_at=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
            metadata={"cwd": str(tmp_path / "outside")},
        )
        denied = make_session(
            "claude-denied",
            "Claude denied",
            created_at=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
            metadata={"cwd": str(cwd / "blocked")},
        )

        codex_agent = mock.MagicMock()
        codex_agent.name = "codex"
        codex_agent.display_name = "Codex"
        codex_agent.get_sessions.return_value = [in_scope, out_of_scope]
        codex_agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
        codex_agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "实现 dry-run"}]}]
        }
        configure_session_data_lease(codex_agent)

        claude_agent = mock.MagicMock()
        claude_agent.name = "claudecode"
        claude_agent.display_name = "Claude Code"
        claude_agent.get_sessions.return_value = [denied]
        claude_agent.get_session_uri.side_effect = lambda session: f"claude://{session.id}"
        claude_agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "被 deny 的会话"}]}]
        }
        configure_session_data_lease(claude_agent)
        collect_config = CollectConfig(
            summary_concurrency=2,
            agent_denies={"claudecode": (str(cwd / "blocked"),)},
        )
        mock_scanner = mock.MagicMock()
        known_codex = mock.MagicMock()
        known_codex.name = "codex"
        known_claude = mock.MagicMock()
        known_claude.name = "claudecode"
        mock_scanner.agents = [known_codex, known_claude]
        mock_scanner.get_available_agents.return_value = [codex_agent, claude_agent]
        configure_scanner_sessions(mock_scanner)
        config_document = make_config_document(collect_config=collect_config)

        with (
            mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document),
            mock.patch("agent_dump.cli.AgentScanner", return_value=mock_scanner),
            mock.patch("agent_dump.collect_workflow.summarize_collect_entries") as mock_summarize,
            mock.patch("agent_dump.cli.request_summary_from_llm") as mock_request_summary,
            mock.patch("agent_dump.collect_workflow.write_collect_markdown") as mock_write,
        ):
            result = handle_collect_mode(collect_operation_from(args))

        assert result == 0
        config_document.ai_config.assert_not_called()
        config_document.collect_config.assert_called_once_with()
        config_document.logging_config.assert_not_called()
        mock_summarize.assert_not_called()
        mock_request_summary.assert_not_called()
        mock_write.assert_not_called()
        codex_agent.lease_cached_session_data.assert_called_once_with(in_scope)
        claude_agent.lease_cached_session_data.assert_not_called()
        assert output_path.exists() is False
        output = capsys.readouterr().out
        assert "Provider 分布：Codex 1" in output
        assert "Session 数：1" in output
        assert str(output_path) in output

    def test_collect_mode_success_shows_stage_progress_in_stderr(self, capsys, tmp_path):
        args = argparse.Namespace(
            collect=True,
            uri=None,
            interactive=False,
            list=False,
            since=None,
            until=None,
            save=None,
        )
        mock_config = mock.MagicMock()
        mock_entry = mock.MagicMock()
        mock_planned_entry = mock.MagicMock()
        mock_entry.agent_display_name = "Codex"
        mock_planned_entry.chunks = (mock.MagicMock(), mock.MagicMock(), mock.MagicMock())

        collect_config = mock.MagicMock(summary_concurrency=4, summary_timeout_seconds=90)
        mock_logger = mock.MagicMock()
        config_document = make_config_document(ai_config=mock_config)

        with mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document):
            with mock.patch.object(config_document, "collect_config", return_value=collect_config):
                with mock.patch.object(config_document, "logging_config", return_value=mock.MagicMock()):
                    with mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=mock_logger):
                        with mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])):
                            with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
                                mock_scanner = mock.MagicMock()
                                mock_scanner.get_available_agents.return_value = [mock.MagicMock(name="codex")]
                                configure_scanner_sessions(mock_scanner)
                                mock_scanner_class.return_value = mock_scanner
                                with mock.patch(
                                    "agent_dump.collect_workflow.collect_entries", return_value=[mock_entry]
                                ) as mock_collect:
                                    with mock.patch(
                                        "agent_dump.collect_workflow.plan_collect_entries",
                                        return_value=([mock_planned_entry], 3),
                                    ):

                                        def _summarize_collect_entries(**kwargs):
                                            kwargs["progress_callback"](
                                                SummarizeChunksProgress(
                                                    current=0,
                                                    total=1,
                                                    concurrency=4,
                                                )
                                            )
                                            kwargs["progress_callback"](
                                                SummarizeChunksProgress(
                                                    current=1,
                                                    total=1,
                                                    concurrency=4,
                                                )
                                            )
                                            kwargs["progress_callback"](MergeSessionsProgress(current=0, total=1))
                                            kwargs["progress_callback"](MergeSessionsProgress(current=1, total=1))
                                            return [mock.MagicMock()]

                                        with mock.patch(
                                            "agent_dump.collect_workflow.summarize_collect_entries",
                                            side_effect=_summarize_collect_entries,
                                        ):
                                            with mock.patch(
                                                "agent_dump.collect_workflow.reduce_collect_summaries",
                                                return_value=mock.MagicMock(),
                                            ):
                                                with mock.patch(
                                                    "agent_dump.collect_workflow.build_collect_final_prompt",
                                                    return_value="prompt",
                                                ):
                                                    with mock.patch(
                                                        "agent_dump.cli.request_summary_from_llm",
                                                        return_value="# collect",
                                                    ):
                                                        output_path = (
                                                            tmp_path / "agent-dump-collect-20260305-20260305.md"
                                                        )
                                                        with mock.patch(
                                                            "agent_dump.collect_workflow.write_collect_markdown",
                                                            return_value=output_path,
                                                        ):
                                                            result = handle_collect_mode(collect_operation_from(args))

        assert result == 0
        assert mock_collect.call_args.kwargs["collect_config"] is collect_config
        assert mock_collect.call_args.kwargs["logger"] is mock_logger
        captured = capsys.readouterr()
        assert "Collect 任务开始" in captured.err
        assert "本次将处理 1 个 session，拆分为 3 个总结单元；并发 4" in captured.err
        assert "正在总结内容：已完成 1/1 个单元，并发 4" in captured.err
        assert "正在合并 session 结果：1/1" in captured.err
        assert "正在生成最终总结：2/2" in captured.err
        assert "正在写入结果文件：1/1" in captured.err
        assert str(output_path) in captured.out
        assert mock_logger.log.call_count >= 2

    def test_collect_mode_passes_resolved_save_path(self, tmp_path):
        args = argparse.Namespace(
            collect=True,
            uri=None,
            interactive=False,
            list=False,
            since="2026-03-01",
            until="2026-03-05",
            save=str(tmp_path / "reports" / "report.md"),
        )
        mock_config = mock.MagicMock()
        mock_entry = mock.MagicMock()
        mock_planned_entry = mock.MagicMock()
        mock_entry.agent_display_name = "Codex"
        mock_planned_entry.chunks = (mock.MagicMock(),)
        output_path = tmp_path / "reports" / "report.md"
        mock_logger = mock.MagicMock()
        config_document = make_config_document(ai_config=mock_config)

        with mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document):
            with mock.patch.object(
                config_document,
                "collect_config",
                return_value=mock.MagicMock(summary_concurrency=4, summary_timeout_seconds=90),
            ):
                with mock.patch.object(config_document, "logging_config", return_value=mock.MagicMock()):
                    with mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=mock_logger):
                        with mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])):
                            with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
                                mock_scanner = mock.MagicMock()
                                mock_scanner.get_available_agents.return_value = [mock.MagicMock(name="codex")]
                                configure_scanner_sessions(mock_scanner)
                                mock_scanner_class.return_value = mock_scanner
                                with mock.patch(
                                    "agent_dump.collect_workflow.collect_entries", return_value=[mock_entry]
                                ):
                                    with mock.patch(
                                        "agent_dump.collect_workflow.plan_collect_entries",
                                        return_value=([mock_planned_entry], 1),
                                    ):
                                        with mock.patch(
                                            "agent_dump.collect_workflow.summarize_collect_entries",
                                            return_value=[mock.MagicMock()],
                                        ):
                                            with mock.patch(
                                                "agent_dump.collect_workflow.reduce_collect_summaries",
                                                return_value=mock.MagicMock(),
                                            ):
                                                with mock.patch(
                                                    "agent_dump.collect_workflow.build_collect_final_prompt",
                                                    return_value="prompt",
                                                ):
                                                    with mock.patch(
                                                        "agent_dump.cli.request_summary_from_llm",
                                                        return_value="# collect",
                                                    ):
                                                        with mock.patch(
                                                            "agent_dump.collect_workflow.write_collect_markdown",
                                                            return_value=output_path,
                                                        ) as mock_write:
                                                            result = handle_collect_mode(collect_operation_from(args))

        assert result == 0
        mock_write.assert_called_once_with(
            "# collect",
            since_date=datetime(2026, 3, 1).date(),
            until_date=datetime(2026, 3, 5).date(),
            output_path=output_path,
        )

    def test_collect_mode_accepts_cursor_agent(self):
        args = argparse.Namespace(
            collect=True,
            uri=None,
            interactive=False,
            list=False,
            since=None,
            until=None,
            save=None,
        )
        mock_config = mock.MagicMock()
        cursor_agent = mock.MagicMock()
        cursor_agent.name = "cursor"
        output_path = Path("collect.md")
        mock_logger = mock.MagicMock()
        config_document = make_config_document(ai_config=mock_config)

        with mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document):
            with mock.patch.object(
                config_document,
                "collect_config",
                return_value=mock.MagicMock(summary_concurrency=4, summary_timeout_seconds=90),
            ):
                with mock.patch.object(config_document, "logging_config", return_value=mock.MagicMock()):
                    with mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=mock_logger):
                        with mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])):
                            with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
                                mock_scanner = mock.MagicMock()
                                mock_scanner.get_available_agents.return_value = [cursor_agent]
                                configure_scanner_sessions(mock_scanner)
                                mock_scanner_class.return_value = mock_scanner
                                with mock.patch(
                                    "agent_dump.collect_workflow.collect_entries",
                                    return_value=[mock.MagicMock()],
                                ) as mock_collect:
                                    with mock.patch(
                                        "agent_dump.collect_workflow.plan_collect_entries",
                                        return_value=([mock.MagicMock()], 1),
                                    ):
                                        with mock.patch(
                                            "agent_dump.collect_workflow.summarize_collect_entries",
                                            return_value=[mock.MagicMock()],
                                        ):
                                            with mock.patch(
                                                "agent_dump.collect_workflow.reduce_collect_summaries",
                                                return_value=mock.MagicMock(),
                                            ):
                                                with mock.patch(
                                                    "agent_dump.collect_workflow.build_collect_final_prompt",
                                                    return_value="prompt",
                                                ):
                                                    with mock.patch(
                                                        "agent_dump.cli.request_summary_from_llm",
                                                        return_value="# collect",
                                                    ):
                                                        with mock.patch(
                                                            "agent_dump.collect_workflow.write_collect_markdown",
                                                            return_value=output_path,
                                                        ):
                                                            result = handle_collect_mode(collect_operation_from(args))

        assert result == 0
        assert mock_collect.call_args.kwargs["session_groups"] == [
            (cursor_agent, cursor_agent.get_sessions.return_value)
        ]
        mock_scanner.get_available_sessions.assert_called_once()

    def test_collect_mode_logs_failure(self, tmp_path):
        args = argparse.Namespace(
            collect=True,
            uri=None,
            interactive=False,
            list=False,
            since=None,
            until=None,
            save=None,
        )
        mock_logger = mock.MagicMock()
        config_document = make_config_document(
            ai_config=mock.MagicMock(),
            collect_config=mock.MagicMock(summary_concurrency=4, summary_timeout_seconds=90),
        )

        with (
            mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document),
            mock.patch.object(config_document, "logging_config", return_value=mock.MagicMock()),
        ):
            with mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=mock_logger):
                with mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])):
                    with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
                        mock_scanner = mock.MagicMock()
                        mock_scanner.get_available_agents.return_value = [mock.MagicMock(name="codex")]
                        configure_scanner_sessions(mock_scanner)
                        mock_scanner_class.return_value = mock_scanner
                        with mock.patch(
                            "agent_dump.collect_workflow.collect_entries", side_effect=RuntimeError("boom")
                        ):
                            result = handle_collect_mode(collect_operation_from(args))

        assert result == 1
        assert mock_logger.log.call_args_list[-1].args[0] == "collect_run_fail"

    def test_resolve_collect_save_path_defaults_to_current_directory_when_missing(self):
        assert (
            resolve_collect_save_path(
                None,
                since_date=datetime(2026, 3, 1).date(),
                until_date=datetime(2026, 3, 5).date(),
            )
            is None
        )

    def test_resolve_collect_save_path_uses_default_filename_for_directory(self, tmp_path):
        path = resolve_collect_save_path(
            str(tmp_path),
            since_date=datetime(2026, 3, 1).date(),
            until_date=datetime(2026, 3, 5).date(),
        )
        assert path == tmp_path / "agent-dump-collect-20260301-20260305.md"

    def test_resolve_collect_save_path_treats_missing_non_suffix_path_as_directory(self, tmp_path):
        path = resolve_collect_save_path(
            str(tmp_path / "reports"),
            since_date=datetime(2026, 3, 1).date(),
            until_date=datetime(2026, 3, 5).date(),
        )
        assert path == tmp_path / "reports" / "agent-dump-collect-20260301-20260305.md"

    def test_resolve_collect_save_path_treats_md_suffix_as_file(self, tmp_path):
        path = resolve_collect_save_path(
            str(tmp_path / "reports" / "report.md"),
            since_date=datetime(2026, 3, 1).date(),
            until_date=datetime(2026, 3, 5).date(),
        )
        assert path == tmp_path / "reports" / "report.md"

    def test_show_collect_progress_non_tty_reports_incremental_progress(self, capsys):
        with mock.patch("sys.stderr.isatty", return_value=False):
            with show_collect_progress() as update_progress:
                update_progress(CollectStartProgress(since="2026-03-01", until="2026-03-05"))
                update_progress(ScanSessionsProgress(current=0, total=2))
                update_progress(ScanSessionsProgress(current=2, total=2))
                update_progress(PlanChunksProgress(current=2, total=2, chunk_total=5))
                update_progress(
                    CollectOverviewProgress(
                        session_count=2,
                        chunk_count=5,
                        concurrency=4,
                        agent_session_counts={"Codex": 2},
                    )
                )
                update_progress(RenderFinalProgress(current=2, total=2))

        captured = capsys.readouterr()
        assert "Collect 任务开始：2026-03-01 ~ 2026-03-05" in captured.err
        assert "正在扫描会话：0/2" in captured.err
        assert "正在扫描会话：2/2" in captured.err
        assert "已完成预处理：2 个 session，拆分为 5 个总结单元" in captured.err
        assert "本次将处理 2 个 session，拆分为 5 个总结单元；并发 4" in captured.err
        assert "Agent 分布：Codex 2" in captured.err
        assert "正在生成最终总结：2/2" in captured.err

    @pytest.mark.parametrize(
        "event",
        [
            CollectStartProgress(since="2026-03-01", until="2026-03-05"),
            CollectOverviewProgress(
                session_count=1,
                chunk_count=1,
                concurrency=1,
                agent_session_counts={"Codex": 1},
            ),
            ScanSessionsProgress(current=1, total=1),
            PlanChunksProgress(current=1, total=1, chunk_total=1),
            SummarizeChunksProgress(current=1, total=1, concurrency=1),
            MergeSessionsProgress(current=1, total=1),
            TreeReductionProgress(level=1, current=1, total=1),
            RenderFinalProgress(current=1, total=1),
            WriteOutputProgress(current=1, total=1),
        ],
    )
    def test_show_collect_progress_formats_every_stage(self, capsys, event: CollectProgressEvent):
        with mock.patch("sys.stderr.isatty", return_value=False):
            with show_collect_progress() as update_progress:
                update_progress(event)

        lines = capsys.readouterr().err.splitlines()
        assert lines
        assert all(not has_unsafe_line_characters(line) for line in lines)

    def test_show_collect_progress_tty_finishes_with_newline(self, capsys):
        with mock.patch("sys.stderr.isatty", return_value=True), show_collect_progress() as update_progress:
            update_progress(SummarizeChunksProgress(current=0, total=2, concurrency=2))
            update_progress(SummarizeChunksProgress(current=2, total=2, concurrency=2))

        captured = capsys.readouterr()
        assert "正在总结内容：已完成 2/2 个单元，并发 2" in captured.err
        assert captured.err.endswith("\n")

    def test_show_collect_progress_tty_clears_spinner_before_overview(self):
        class FakeStderr:
            def __init__(self) -> None:
                self.chunks: list[str] = []

            def isatty(self) -> bool:
                return True

            def write(self, text: str) -> int:
                self.chunks.append(text)
                return len(text)

            def flush(self) -> None:
                return None

        class FakeThread:
            def __init__(self, target, daemon: bool = False) -> None:
                self.target = target
                self.daemon = daemon

            def start(self) -> None:
                return None

            def join(self, timeout: float | None = None) -> None:
                return None

        fake_stderr = FakeStderr()
        expected_progress = "正在总结内容：已完成 1/2 个单元，并发 2"

        with (
            mock.patch("sys.stderr", fake_stderr),
            mock.patch("agent_dump.collect_workflow.threading.Thread", FakeThread),
        ):
            with show_collect_progress() as update_progress:
                update_progress(
                    SummarizeChunksProgress(
                        current=1,
                        total=2,
                        concurrency=2,
                    )
                )
                update_progress(
                    CollectOverviewProgress(
                        session_count=2,
                        chunk_count=5,
                        concurrency=2,
                        agent_session_counts={"Codex": 2},
                    )
                )

        output = "".join(fake_stderr.chunks)
        assert f"\r{' ' * (len(expected_progress) + 4)}\r" in output
        assert "本次将处理 2 个 session，拆分为 5 个总结单元；并发 2" in output
