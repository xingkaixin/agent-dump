"""Tests for collect diagnostics logging."""

from unittest import mock

from locale_helpers import ALL_LANGUAGES, Keys, expect
import pytest

from agent_dump.collect_logging import CollectLogger, create_collect_logger
from agent_dump.collect_workflow import _report_collect_log_write_error
from agent_dump.config import LoggingConfig


def test_collect_logger_reports_first_write_failure_once(tmp_path) -> None:
    log_path = tmp_path / "collect.log"
    on_write_error = mock.Mock()
    logger = CollectLogger(
        enabled=True,
        path=log_path,
        run_id="run-1",
        on_write_error=on_write_error,
    )

    with mock.patch(
        "agent_dump.collect_logging.open_private_append",
        side_effect=PermissionError("read-only filesystem"),
    ) as open_log:
        logger.log("first")
        logger.log("second")

    open_log.assert_called_once_with(log_path)
    on_write_error.assert_called_once()
    reported_path, reported_error = on_write_error.call_args.args
    assert reported_path == log_path
    assert isinstance(reported_error, PermissionError)
    assert str(reported_error) == "read-only filesystem"


def test_collect_logger_ignores_error_handler_io_failure(tmp_path) -> None:
    logger = CollectLogger(
        enabled=True,
        path=tmp_path / "collect.log",
        on_write_error=mock.Mock(side_effect=BrokenPipeError("closed stderr")),
    )

    with mock.patch(
        "agent_dump.collect_logging.open_private_append",
        side_effect=PermissionError("read-only filesystem"),
    ):
        logger.log("event")


def test_create_collect_logger_preserves_disabled_config(tmp_path) -> None:
    on_write_error = mock.Mock()

    logger = create_collect_logger(
        LoggingConfig(enabled=False, path=tmp_path / "collect.log"),
        on_write_error=on_write_error,
    )

    logger.log("event")
    assert logger.enabled is False
    on_write_error.assert_not_called()


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_collect_log_write_failure_is_localized(language, use_language, capsys, tmp_path) -> None:
    use_language(language)
    log_path = tmp_path / "collect.log"

    _report_collect_log_write_error(log_path, PermissionError("read-only filesystem"))

    assert (
        expect(
            Keys.COLLECT_LOG_WRITE_FAILED,
            path=log_path,
            error="read-only filesystem",
        )
        in capsys.readouterr().err
    )
