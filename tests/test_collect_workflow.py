from datetime import date
from unittest import mock

from locale_helpers import ALL_LANGUAGES, Keys, expect_contains
import pytest

from agent_dump.collect_models import CollectFailurePhase, CollectMode, CollectRunStats
from agent_dump.collect_workflow import handle_collect_mode
from agent_dump.command_plan import CollectOperation


def _run_collect_with_failure(failing_step: str) -> tuple[int, mock.MagicMock, mock.MagicMock]:
    operation = CollectOperation(
        days=None,
        since=None,
        until=None,
        save=None,
        dry_run=False,
        collect_mode=CollectMode.PM,
        query_spec=None,
    )
    config_document = mock.MagicMock()
    config_document.ai_config.return_value = mock.MagicMock()
    config_document.collect_config.return_value = mock.MagicMock(
        summary_concurrency=4,
        summary_timeout_seconds=90,
    )
    scanner = mock.MagicMock()
    agent = mock.MagicMock(name="codex")
    scanner.get_available_agents.return_value = [agent]
    scanner.get_available_sessions.return_value = [(agent, [])]
    logger = mock.MagicMock()
    structured_requester = mock.MagicMock()
    error = RuntimeError(f"{failing_step} failed")
    planned_entry = mock.MagicMock()
    planned_entry.collect_entry.is_truncated = True

    with (
        mock.patch(
            "agent_dump.collect_workflow.resolve_collect_date_range",
            return_value=(date(2026, 1, 1), date(2026, 1, 1)),
        ),
        mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document),
        mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])),
        mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=logger),
        mock.patch(
            "agent_dump.collect_workflow.collect_entries",
            return_value=[mock.MagicMock()],
            side_effect=error if failing_step == "read" else None,
        ),
        mock.patch("agent_dump.collect_workflow.plan_collect_entries", return_value=([planned_entry], 1)),
        mock.patch(
            "agent_dump.collect_workflow.build_collect_run_stats",
            return_value=CollectRunStats(
                since="2026-01-01",
                until="2026-01-01",
                agent_session_counts={"Codex": 1},
                session_count=1,
                chunk_count=1,
                concurrency=4,
            ),
        ),
        mock.patch(
            "agent_dump.collect_workflow.summarize_collect_entries",
            return_value=[mock.MagicMock()],
            side_effect=error if failing_step == "summarize" else None,
        ) as mock_summarize,
        mock.patch(
            "agent_dump.collect_workflow.reduce_collect_summaries",
            return_value=mock.MagicMock(),
            side_effect=error if failing_step == "render" else None,
        ) as mock_reduce,
        mock.patch(
            "agent_dump.collect_workflow.build_collect_final_prompt",
            return_value="prompt",
        ) as mock_build_final_prompt,
        mock.patch("agent_dump.collect_workflow.write_collect_markdown", return_value=mock.MagicMock()),
    ):
        result = handle_collect_mode(
            operation,
            scanner_factory=lambda: scanner,
            request_summary=lambda *_args, **_kwargs: "# summary",
            request_structured_summary=structured_requester,
        )

    if failing_step != "read":
        assert mock_summarize.call_args.kwargs["request_structured_summary"] is structured_requester
    if failing_step not in {"read", "summarize"}:
        assert mock_reduce.call_args.kwargs["request_structured_summary"] is structured_requester

    return result, logger, mock_build_final_prompt


@pytest.mark.parametrize("language", ALL_LANGUAGES)
@pytest.mark.parametrize(
    ("failing_step", "failure_phase", "message_key"),
    [
        ("read", CollectFailurePhase.READ, Keys.COLLECT_READ_FAILED),
        ("summarize", CollectFailurePhase.SUMMARIZE, Keys.COLLECT_API_FAILED),
        ("render", CollectFailurePhase.RENDER, Keys.COLLECT_API_FAILED),
    ],
)
def test_collect_reports_failure_from_the_stage_that_raised(
    language,
    use_language,
    capsys,
    failing_step: str,
    failure_phase: CollectFailurePhase,
    message_key: str,
) -> None:
    use_language(language)

    result, logger, _ = _run_collect_with_failure(failing_step)

    assert result == 1
    assert expect_contains(capsys.readouterr().out, message_key, error=f"{failing_step} failed")
    logger.log.assert_called_with(
        "collect_run_fail",
        phase=failure_phase.value,
        error=f"{failing_step} failed",
    )


def test_collect_finish_log_uses_run_stats_session_count(capsys) -> None:
    result, logger, _ = _run_collect_with_failure("success")
    capsys.readouterr()

    finish_call = next(call for call in logger.log.call_args_list if call.args[0] == "collect_run_finish")
    assert result == 0
    assert finish_call.kwargs["session_count"] == 1


def test_collect_derives_truncation_from_planned_entries(capsys) -> None:
    result, _, mock_build_final_prompt = _run_collect_with_failure("success")
    capsys.readouterr()

    assert result == 0
    assert mock_build_final_prompt.call_args.kwargs["has_truncated"] is True


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_collect_reports_output_write_failure(language, use_language, capsys) -> None:
    use_language(language)
    operation = CollectOperation(
        days=None,
        since=None,
        until=None,
        save=None,
        dry_run=False,
        collect_mode=CollectMode.PM,
        query_spec=None,
    )
    config_document = mock.MagicMock()
    config_document.ai_config.return_value = mock.MagicMock()
    config_document.collect_config.return_value = mock.MagicMock(
        summary_concurrency=4,
        summary_timeout_seconds=90,
    )
    scanner = mock.MagicMock()
    agent = mock.MagicMock(name="codex")
    scanner.get_available_agents.return_value = [agent]
    scanner.get_available_sessions.return_value = [(agent, [])]
    logger = mock.MagicMock()

    with (
        mock.patch(
            "agent_dump.collect_workflow.resolve_collect_date_range",
            return_value=(date(2026, 1, 1), date(2026, 1, 1)),
        ),
        mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document),
        mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])),
        mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=logger),
        mock.patch("agent_dump.collect_workflow.collect_entries", return_value=[mock.MagicMock()]),
        mock.patch("agent_dump.collect_workflow.plan_collect_entries", return_value=([mock.MagicMock()], 1)),
        mock.patch("agent_dump.collect_workflow.build_collect_run_stats", return_value=mock.MagicMock()),
        mock.patch("agent_dump.collect_workflow.summarize_collect_entries", return_value=[mock.MagicMock()]),
        mock.patch("agent_dump.collect_workflow.reduce_collect_summaries", return_value=mock.MagicMock()),
        mock.patch("agent_dump.collect_workflow.build_collect_final_prompt", return_value="prompt"),
        mock.patch(
            "agent_dump.collect_workflow.write_collect_markdown",
            side_effect=PermissionError("read-only filesystem"),
        ),
    ):
        result = handle_collect_mode(
            operation,
            scanner_factory=lambda: scanner,
            request_summary=lambda *_args, **_kwargs: "# summary",
        )

    output = capsys.readouterr().out
    assert result == 1
    assert expect_contains(output, Keys.COLLECT_WRITE_FAILED, error="read-only filesystem")
    assert not expect_contains(output, Keys.COLLECT_API_FAILED, error="read-only filesystem")
    logger.log.assert_called_with(
        "collect_run_fail",
        phase=CollectFailurePhase.WRITE.value,
        error="read-only filesystem",
    )
