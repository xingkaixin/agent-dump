from datetime import date
from unittest import mock

from locale_helpers import ALL_LANGUAGES, Keys, expect_contains
import pytest

from agent_dump.collect_models import CollectFailurePhase, CollectMode
from agent_dump.collect_workflow import handle_collect_mode
from agent_dump.command_plan import CollectOperation


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
    scanner.get_available_agents.return_value = [mock.MagicMock(name="codex")]
    logger = mock.MagicMock()

    with (
        mock.patch(
            "agent_dump.collect_workflow.resolve_collect_date_range",
            return_value=(date(2026, 1, 1), date(2026, 1, 1)),
        ),
        mock.patch("agent_dump.collect_workflow.load_config_document", return_value=config_document),
        mock.patch("agent_dump.collect_workflow.validate_ai_config", return_value=(True, [])),
        mock.patch("agent_dump.collect_workflow.create_collect_logger", return_value=logger),
        mock.patch("agent_dump.collect_workflow.collect_entries", return_value=([mock.MagicMock()], False)),
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
