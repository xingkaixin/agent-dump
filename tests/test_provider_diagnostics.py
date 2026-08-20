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


def test_provider_diagnostic_renderer_sanitizes_untrusted_fields() -> None:
    diagnostic = ProviderDiagnostic(
        message_key=Keys.WARN_TITLE_EXTRACT_FAILED,
        fields={"error": "bad\x1b[2K\rFORGED\u202e"},
    )

    rendered = render_provider_diagnostic(diagnostic)

    assert "FORGED" in rendered
    assert "\x1b" not in rendered
    assert "\r" not in rendered
