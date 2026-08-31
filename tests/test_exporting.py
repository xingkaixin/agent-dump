from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tracemalloc
from unittest import mock

import pytest

from agent_dump import exporting
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.exporting import (
    ExportFailure,
    ExportPathCollisionError,
    ExportRunResult,
    ExportRunStatus,
    ExportSuccess,
    execute_exports,
)
from agent_dump.output_formats import FileOutputFormat
from agent_dump.private_files import PRIVATE_DIR_MODE, PRIVATE_FILE_MODE
from agent_dump.session_data import MAX_COMPLETED_SESSION_DATA_ENTRIES


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


def test_empty_export_run_has_explicit_status() -> None:
    assert ExportRunResult(()).status is ExportRunStatus.EMPTY


def test_execute_exports_retains_success_and_failure_outcomes(tmp_path: Path) -> None:
    agent = mock.MagicMock()
    first = make_session("first", "First")
    second = make_session("second", "Second")
    agent.export_session.side_effect = [tmp_path / "first.json", RuntimeError("failed")]

    result = execute_exports(agent, [first, second], ["json"], lambda _: tmp_path)

    assert result.status is ExportRunStatus.PARTIAL
    assert result.exported_paths == (tmp_path / "first.json",)
    assert isinstance(result.attempts[0], ExportSuccess)
    assert isinstance(result.attempts[1], ExportFailure)
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

    assert result.status is ExportRunStatus.SUCCEEDED
    assert result.exported_paths == (output_path,)
    assert isinstance(result.attempts[0], ExportSuccess)
    assert json.loads(output_path.read_text(encoding="utf-8"))["summary"] == "# Summary"
    replace.assert_called_once()


def test_execute_exports_rejects_duplicate_targets_before_writing(tmp_path: Path) -> None:
    agent = ExportingTestAgent()
    first = make_session("first", "First")
    second = make_session("second", "Second")

    with mock.patch("agent_dump.exporting.get_session_export_path", return_value=tmp_path / "duplicate.json"):
        result = execute_exports(agent, [first, second], ["json"], lambda _: tmp_path)

    assert result.status is ExportRunStatus.FAILED
    assert not list(tmp_path.iterdir())
    assert all(
        isinstance(attempt, ExportFailure) and isinstance(attempt.error, ExportPathCollisionError)
        for attempt in result.attempts
    )


def test_markdown_batch_keeps_full_payload_memory_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ExportingTestAgent()
    payload_size = 256 * 1024
    sessions = [make_session(f"session-{index}", "Session") for index in range(100)]
    monkeypatch.setattr(
        agent, "get_session_data", lambda session: {"id": session.id, "messages": [], "blob": bytearray(payload_size)}
    )

    tracemalloc.start()
    try:
        baseline, _ = tracemalloc.get_traced_memory()
        result = execute_exports(agent, sessions, ["markdown"], lambda _: tmp_path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result.status is ExportRunStatus.SUCCEEDED
    assert len(result) == len(sessions)
    assert all(path.is_file() for path in result.exported_paths)
    assert peak - baseline < payload_size * (MAX_COMPLETED_SESSION_DATA_ENTRIES + 16)


@pytest.mark.parametrize("formats", [["json", "markdown"], ["markdown", "json"]])
def test_multiple_formats_reuse_one_provider_read(tmp_path: Path, formats: list[FileOutputFormat]) -> None:
    agent = ExportingTestAgent()
    session = make_session("session", "Session")
    with mock.patch.object(agent, "get_session_data", wraps=agent.get_session_data) as load:
        result = execute_exports(agent, [session], formats, lambda _: tmp_path)

    assert result.status is ExportRunStatus.SUCCEEDED
    assert len(result) == 2
    load.assert_called_once_with(session)


@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_export_uses_prepared_payload_without_loading(tmp_path: Path, output_format: FileOutputFormat) -> None:
    agent = ExportingTestAgent()
    session = make_session("session", "Session")
    prepared = {"messages": [{"role": "user", "parts": [{"type": "text", "text": "prepared body"}]}]}

    with mock.patch.object(agent, "get_session_data", side_effect=AssertionError("unexpected read")) as load:
        result = execute_exports(
            agent, [session], [output_format], lambda _: tmp_path, prepared_session_data={session.id: prepared}
        )

    assert result.status is ExportRunStatus.SUCCEEDED
    assert "prepared body" in result.exported_paths[0].read_text(encoding="utf-8")
    load.assert_not_called()


@pytest.mark.parametrize("formats", [["json", "markdown"], ["markdown", "json"]])
@pytest.mark.parametrize("prepared", [False, True])
def test_exports_keep_one_snapshot_when_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, formats: list[FileOutputFormat], prepared: bool
) -> None:
    agent = ExportingTestAgent()
    session = make_session("session", "Session")
    session.source_path = tmp_path / "source.txt"
    session.source_path.write_text("old body", encoding="utf-8")
    monkeypatch.setattr(agent, "get_session_change_sources", lambda value: (value.source_path,))

    def read_data(value: Session) -> dict:
        return {
            "messages": [
                {"role": "user", "parts": [{"type": "text", "text": value.source_path.read_text(encoding="utf-8")}]}
            ]
        }

    monkeypatch.setattr(agent, "get_session_data", read_data)
    initial_data = agent.get_cached_session_data(session) if prepared else None
    if prepared:
        session.source_path.write_text("new body before export", encoding="utf-8")
    original_export = exporting.export_session_in_format

    def export_then_update(*args, **kwargs):
        path = original_export(*args, **kwargs)
        session.source_path.write_text("new body between formats", encoding="utf-8")
        return path

    monkeypatch.setattr(exporting, "export_session_in_format", export_then_update)
    with mock.patch.object(agent, "get_session_data", wraps=agent.get_session_data) as read:
        result = execute_exports(
            agent,
            [session],
            formats,
            lambda _: tmp_path / "out",
            prepared_session_data={session.id: initial_data} if initial_data is not None else None,
            summaries={session.id: "Summary of old body"} if prepared else None,
        )

    assert result.status is ExportRunStatus.SUCCEEDED
    assert read.call_count == (0 if prepared else 1)
    for path in result.exported_paths:
        text = path.read_text(encoding="utf-8")
        assert "old body" in text
        assert "new body" not in text
        if prepared and path.suffix == ".json":
            assert json.loads(text)["summary"] == "Summary of old body"


def test_snapshot_read_failure_does_not_block_raw_export(tmp_path: Path) -> None:
    agent = ExportingTestAgent()
    session = make_session("session", "Session")
    session.source_path = tmp_path / "source.jsonl"
    session.source_path.write_text("raw source", encoding="utf-8")

    with mock.patch.object(agent, "get_session_data", side_effect=ValueError("cannot parse")) as read:
        result = execute_exports(agent, [session], ["json", "raw", "markdown"], lambda _: tmp_path / "out")

    assert result.status is ExportRunStatus.PARTIAL
    assert [type(attempt) for attempt in result.attempts] == [ExportFailure, ExportSuccess, ExportFailure]
    assert result.exported_paths[0].read_text(encoding="utf-8") == "raw source"
    read.assert_called_once_with(session)


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
