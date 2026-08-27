from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import (
    RecoverableDiagnostic,
    emit_recoverable_diagnostic,
    render_recoverable_diagnostic,
)
from agent_dump.i18n import Keys
from agent_dump.scanner import AgentScanner


class DiagnosticAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("diagnostic", "Diagnostic")

    def scan(self) -> list[Session]:
        return []

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        del days
        self._report_diagnostic(Keys.WARN_TITLE_EXTRACT_FAILED, error="bad title")
        return []

    def get_session_data(self, session: Session) -> dict:
        del session
        return {"messages": []}


class ConcurrentDiagnosticAgent(DiagnosticAgent):
    def __init__(self) -> None:
        super().__init__()
        self._barrier = Barrier(2)

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        self._barrier.wait()
        self._report_diagnostic(Keys.WARN_TITLE_EXTRACT_FAILED, error="bad title", caller=days)
        return []


def test_direct_provider_use_has_no_terminal_side_effect(capsys) -> None:
    agent = DiagnosticAgent()
    AgentScanner([agent])

    agent.get_sessions()

    assert capsys.readouterr().err == ""


def test_emit_recoverable_diagnostic_uses_shared_event_model() -> None:
    diagnostics: list[RecoverableDiagnostic] = []

    emit_recoverable_diagnostic(diagnostics.append, "warning", reason="fallback")
    emit_recoverable_diagnostic(None, "ignored")

    assert diagnostics == [RecoverableDiagnostic(message_key="warning", fields={"reason": "fallback"})]


def test_scanner_attaches_terminal_diagnostic_boundary(capsys) -> None:
    agent = DiagnosticAgent()
    scanner = AgentScanner([agent])

    scanner.get_sessions()

    assert "bad title" in capsys.readouterr().err


def test_scanner_can_disable_provider_diagnostics(capsys) -> None:
    agent = DiagnosticAgent()
    scanner = AgentScanner([agent], diagnostic_sink=None)

    scanner.get_sessions()

    assert capsys.readouterr().err == ""


def test_scanner_diagnostic_destination_does_not_persist_after_operation() -> None:
    agent = DiagnosticAgent()
    diagnostics: list[RecoverableDiagnostic] = []
    scanner = AgentScanner([agent], diagnostic_sink=diagnostics.append)

    scanner.get_sessions()
    agent.get_sessions()

    assert len(diagnostics) == 1


def test_scanner_read_context_restores_the_previous_caller_after_failure() -> None:
    agent = DiagnosticAgent()
    outer_diagnostics: list[RecoverableDiagnostic] = []
    inner_diagnostics: list[RecoverableDiagnostic] = []
    outer = AgentScanner([agent], diagnostic_sink=outer_diagnostics.append)
    inner = AgentScanner([agent], diagnostic_sink=inner_diagnostics.append)

    with outer.diagnostic_context():
        agent.get_sessions()
        with pytest.raises(RuntimeError, match="read failed"), inner.diagnostic_context():
            agent.get_sessions()
            raise RuntimeError("read failed")
        agent.get_sessions()
        with AgentScanner([agent], diagnostic_sink=None).diagnostic_context():
            agent.get_sessions()
    agent.get_sessions()

    assert len(outer_diagnostics) == 2
    assert len(inner_diagnostics) == 1


def test_scanners_keep_their_own_provider_diagnostic_destinations() -> None:
    agent = DiagnosticAgent()
    first_diagnostics: list[RecoverableDiagnostic] = []
    second_diagnostics: list[RecoverableDiagnostic] = []
    first_scanner = AgentScanner([agent], diagnostic_sink=first_diagnostics.append)
    second_scanner = AgentScanner([agent], diagnostic_sink=second_diagnostics.append)

    first_scanner.get_sessions()
    second_scanner.get_sessions()

    assert [diagnostic.fields["error"] for diagnostic in first_diagnostics] == ["bad title"]
    assert [diagnostic.fields["error"] for diagnostic in second_diagnostics] == ["bad title"]


def test_concurrent_scanners_keep_their_own_provider_diagnostic_destinations() -> None:
    agent = ConcurrentDiagnosticAgent()
    first_diagnostics: list[RecoverableDiagnostic] = []
    second_diagnostics: list[RecoverableDiagnostic] = []
    first_scanner = AgentScanner([agent], diagnostic_sink=first_diagnostics.append)
    second_scanner = AgentScanner([agent], diagnostic_sink=second_diagnostics.append)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_scanner.get_sessions, 1)
        second = executor.submit(second_scanner.get_sessions, 2)
        first.result()
        second.result()

    assert [diagnostic.fields["caller"] for diagnostic in first_diagnostics] == [1]
    assert [diagnostic.fields["caller"] for diagnostic in second_diagnostics] == [2]


def test_recoverable_diagnostic_renderer_sanitizes_untrusted_fields() -> None:
    diagnostic = RecoverableDiagnostic(
        message_key=Keys.WARN_TITLE_EXTRACT_FAILED,
        fields={"error": "bad\x1b[2K\rFORGED\u202e"},
    )

    rendered = render_recoverable_diagnostic(diagnostic)

    assert "FORGED" in rendered
    assert "\x1b" not in rendered
    assert "\r" not in rendered
