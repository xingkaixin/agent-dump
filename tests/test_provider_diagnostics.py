from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.i18n import Keys
from agent_dump.provider_diagnostics import ProviderDiagnostic, render_provider_diagnostic
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
    DiagnosticAgent().get_sessions()

    assert capsys.readouterr().err == ""


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


def test_scanners_keep_their_own_provider_diagnostic_destinations() -> None:
    agent = DiagnosticAgent()
    first_diagnostics: list[ProviderDiagnostic] = []
    second_diagnostics: list[ProviderDiagnostic] = []
    first_scanner = AgentScanner([agent], diagnostic_sink=first_diagnostics.append)
    second_scanner = AgentScanner([agent], diagnostic_sink=second_diagnostics.append)

    first_scanner.get_sessions()
    second_scanner.get_sessions()

    assert [diagnostic.fields["error"] for diagnostic in first_diagnostics] == ["bad title"]
    assert [diagnostic.fields["error"] for diagnostic in second_diagnostics] == ["bad title"]


def test_concurrent_scanners_keep_their_own_provider_diagnostic_destinations() -> None:
    agent = ConcurrentDiagnosticAgent()
    first_diagnostics: list[ProviderDiagnostic] = []
    second_diagnostics: list[ProviderDiagnostic] = []
    first_scanner = AgentScanner([agent], diagnostic_sink=first_diagnostics.append)
    second_scanner = AgentScanner([agent], diagnostic_sink=second_diagnostics.append)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_scanner.get_sessions, 1)
        second = executor.submit(second_scanner.get_sessions, 2)
        first.result()
        second.result()

    assert [diagnostic.fields["caller"] for diagnostic in first_diagnostics] == [1]
    assert [diagnostic.fields["caller"] for diagnostic in second_diagnostics] == [2]


def test_provider_diagnostic_renderer_sanitizes_untrusted_fields() -> None:
    diagnostic = ProviderDiagnostic(
        message_key=Keys.WARN_TITLE_EXTRACT_FAILED,
        fields={"error": "bad\x1b[2K\rFORGED\u202e"},
    )

    rendered = render_provider_diagnostic(diagnostic)

    assert "FORGED" in rendered
    assert "\x1b" not in rendered
    assert "\r" not in rendered
