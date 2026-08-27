"""Recoverable provider diagnostics across complete session read workflows."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timezone
from pathlib import Path
from threading import Barrier
from typing import Any
from unittest import mock

from locale_helpers import Keys, expect
import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.codex import CodexAgent
from agent_dump.cli import main
from agent_dump.collect_sessions import collect_entries
from agent_dump.diagnostics import RecoverableDiagnostic
from agent_dump.query_filter import QuerySpec, select_session_groups
from agent_dump.search_index import SearchIndex


@pytest.fixture
def damaged_session(codex_session_tree: dict[str, Any]) -> tuple[CodexAgent, Session, RecoverableDiagnostic]:
    source = codex_session_tree["session_file"]
    contents = source.read_text(encoding="utf-8")
    line_number = contents.count("\n") + 1
    source.write_text(contents + '{"broken":\n', encoding="utf-8")
    agent = CodexAgent()
    session = agent.get_sessions(days=None)[0]
    diagnostic = RecoverableDiagnostic(
        Keys.WARN_JSONL_RECORDS_SKIPPED,
        {"path": str(source), "count": 1, "lines": str(line_number)},
    )
    return agent, session, diagnostic


@pytest.mark.parametrize("output_format", ["print", "json", "markdown", "print,json,markdown"])
def test_uri_reports_damaged_records_once_across_formats(
    damaged_session: tuple[CodexAgent, Session, RecoverableDiagnostic],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    agent, session, diagnostic = damaged_session
    with mock.patch(
        "sys.argv",
        ["agent-dump", agent.get_session_uri(session), "--format", output_format, "--output", str(tmp_path / "export")],
    ):
        assert main() == 0

    assert capsys.readouterr().err.count(expect(diagnostic.message_key, **diagnostic.fields)) == 1


def test_interactive_export_reports_damaged_records(
    damaged_session: tuple[CodexAgent, Session, RecoverableDiagnostic],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, diagnostic = damaged_session
    with (
        mock.patch("sys.argv", ["agent-dump", "--interactive", "-days", "36500", "--output", str(tmp_path / "export")]),
        mock.patch(
            "agent_dump.session_workflow.select_sessions_interactive",
            side_effect=lambda sessions, *args, **kwargs: sessions,
        ),
    ):
        assert main() == 0

    assert expect(diagnostic.message_key, **diagnostic.fields) in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [["--search", "超时"], ["--reindex"], ["--stats", "-query", "超时 role:user"]])
def test_search_and_maintenance_report_damaged_records(
    damaged_session: tuple[CodexAgent, Session, RecoverableDiagnostic],
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    _, _, diagnostic = damaged_session
    with mock.patch("sys.argv", ["agent-dump", *arguments, "-days", "36500"]):
        assert main() == 0

    assert expect(diagnostic.message_key, **diagnostic.fields) in capsys.readouterr().err


@pytest.mark.parametrize("roles", [None, frozenset({"user"})])
@pytest.mark.parametrize("indexed", [True, False])
def test_query_routes_provider_diagnostics_to_its_sink(
    damaged_session: tuple[CodexAgent, Session, RecoverableDiagnostic],
    tmp_path: Path,
    roles: frozenset[str] | None,
    indexed: bool,
) -> None:
    agent, session, diagnostic = damaged_session
    diagnostics: list[RecoverableDiagnostic] = []
    index = SearchIndex(tmp_path / "index.db") if indexed else mock.MagicMock(is_available=False)
    matches = select_session_groups(
        [(agent, [session])],
        QuerySpec(None, "超时", None, roles, None),
        search_index=index,
        diagnostic_sink=diagnostics.append,
    )

    assert [match.session.id for match in matches] == [session.id]
    assert diagnostics == [diagnostic]
    agent.get_session_data(session)
    assert diagnostics == [diagnostic]


def test_collect_routes_worker_diagnostics_to_its_sink(
    damaged_session: tuple[CodexAgent, Session, RecoverableDiagnostic],
) -> None:
    agent, session, diagnostic = damaged_session
    diagnostics: list[RecoverableDiagnostic] = []
    entries = collect_entries(
        session_groups=[(agent, [session])],
        since_date=session.created_at.date(),
        until_date=session.created_at.date(),
        local_tz=timezone.utc,
        diagnostic_sink=diagnostics.append,
    )

    assert [entry.session_id for entry in entries] == [session.id]
    assert diagnostics == [diagnostic]
    agent.get_session_data(session)
    assert diagnostics == [diagnostic]


def test_collect_dry_run_reports_damaged_records(
    damaged_session: tuple[CodexAgent, Session, RecoverableDiagnostic], capsys: pytest.CaptureFixture[str]
) -> None:
    _, session, diagnostic = damaged_session
    day = session.created_at.date().isoformat()
    with mock.patch("sys.argv", ["agent-dump", "--collect", "--dry-run", "--since", day, "--until", day]):
        assert main() == 0

    assert expect(diagnostic.message_key, **diagnostic.fields) in capsys.readouterr().err


def test_parallel_index_workers_keep_each_callers_sink(
    damaged_session: tuple[CodexAgent, Session, RecoverableDiagnostic],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, session, _ = damaged_session
    barrier = Barrier(2)
    first_diagnostics: list[RecoverableDiagnostic] = []
    second_diagnostics: list[RecoverableDiagnostic] = []

    def read(selected: Session) -> dict[str, Any]:
        barrier.wait(timeout=5)
        agent._report_diagnostic(Keys.WARN_MESSAGE_CONVERT_FAILED, error=selected.id)
        return {"messages": []}

    monkeypatch.setattr(agent, "get_session_data", read)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            SearchIndex(tmp_path / "first.db").update,
            agent,
            [replace(session, id="first")],
            diagnostic_sink=first_diagnostics.append,
        )
        second = executor.submit(
            SearchIndex(tmp_path / "second.db").update,
            agent,
            [replace(session, id="second")],
            diagnostic_sink=second_diagnostics.append,
        )
        assert first.result() == second.result() == (1, 0)

    assert [diagnostic.fields["error"] for diagnostic in first_diagnostics] == ["first"]
    assert [diagnostic.fields["error"] for diagnostic in second_diagnostics] == ["second"]
