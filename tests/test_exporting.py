from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_dump.agents.base import Session
from agent_dump.exporting import execute_exports


def make_session(session_id: str, title: str) -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        id=session_id,
        title=title,
        created_at=now,
        updated_at=now,
        source_path=Path(f"/tmp/{session_id}.jsonl"),
        metadata={},
    )


def test_execute_exports_retains_success_and_failure_outcomes(tmp_path: Path) -> None:
    agent = mock.MagicMock()
    first = make_session("first", "First")
    second = make_session("second", "Second")
    agent.export_session.side_effect = [tmp_path / "first.json", RuntimeError("failed")]

    result = execute_exports(agent, [first, second], ["json"], lambda _: tmp_path)

    assert result.had_success is True
    assert result.all_failed is False
    assert result.exported_paths == (tmp_path / "first.json",)
    assert result.attempts[0].succeeded is True
    assert result.attempts[1].succeeded is False
    assert isinstance(result.attempts[1].error, RuntimeError)


def test_execute_exports_records_summary_failure_without_losing_file(tmp_path: Path) -> None:
    agent = mock.MagicMock()
    session = make_session("session-001", "Session")
    output_path = tmp_path / "session-001.json"
    agent.export_session.return_value = output_path

    with mock.patch("agent_dump.exporting.apply_summary_to_json_export", side_effect=RuntimeError("rewrite failed")):
        result = execute_exports(
            agent,
            [session],
            ["json"],
            lambda _: tmp_path,
            summaries={session.id: "# Summary"},
        )

    assert result.had_success is True
    assert result.exported_paths == (output_path,)
    assert isinstance(result.attempts[0].error, RuntimeError)
