from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.exporting import ExportPathCollisionError, execute_exports
from agent_dump.private_files import PRIVATE_DIR_MODE, PRIVATE_FILE_MODE


class ExportingTestAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("test", "Test")

    def scan(self) -> list[Session]:
        return []

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        return []

    def get_session_data(self, session: Session) -> dict:
        return {"id": session.id, "messages": []}


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


def test_execute_exports_writes_summary_with_initial_json_export(tmp_path: Path) -> None:
    agent = ExportingTestAgent()
    session = make_session("session-001", "Session")
    output_path = tmp_path / "session-001.json"

    with mock.patch("agent_dump.private_files.os.replace", wraps=os.replace) as replace:
        result = execute_exports(
            agent,
            [session],
            ["json"],
            lambda _: tmp_path,
            summaries={session.id: "# Summary"},
        )

    assert result.had_success is True
    assert result.exported_paths == (output_path,)
    assert result.attempts[0].error is None
    assert json.loads(output_path.read_text(encoding="utf-8"))["summary"] == "# Summary"
    replace.assert_called_once()


def test_execute_exports_rejects_duplicate_targets_before_writing(tmp_path: Path) -> None:
    agent = ExportingTestAgent()
    first = make_session("first", "First")
    second = make_session("second", "Second")

    with mock.patch("agent_dump.exporting.get_session_export_path", return_value=tmp_path / "duplicate.json"):
        result = execute_exports(agent, [first, second], ["json"], lambda _: tmp_path)

    assert result.all_failed is True
    assert not list(tmp_path.iterdir())
    assert all(isinstance(attempt.error, ExportPathCollisionError) for attempt in result.attempts)


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes are not meaningful on Windows")
def test_execute_exports_keeps_new_artifacts_owner_only(tmp_path: Path) -> None:
    output_dir = tmp_path / "sessions" / "test"
    previous_umask = os.umask(0o022)
    try:
        result = execute_exports(
            ExportingTestAgent(),
            [make_session("session-001", "Session")],
            ["json"],
            lambda _: output_dir,
        )
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(output_dir.stat().st_mode) == PRIVATE_DIR_MODE
    assert stat.S_IMODE(result.exported_paths[0].stat().st_mode) == PRIVATE_FILE_MODE
