from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from agent_dump.agents.base import Session
from agent_dump.agents.codex import CodexAgent
from agent_dump.agents.file_sessions import FileSessionAgent
from agent_dump.i18n import Keys
from agent_dump.provider_diagnostics import ProviderDiagnostic
from agent_dump.scanner import AgentScanner


class FailingFileAgent(FileSessionAgent):
    def __init__(self, root: Path) -> None:
        super().__init__("files", "Files")
        self.base_path = root
        self.file_discovery_count = 0

    def _iter_session_files(self) -> Iterator[Path]:
        self.file_discovery_count += 1
        if self.base_path is None:
            return iter(())
        return iter(sorted(self.base_path.glob("*.jsonl")))

    def _session_file_candidates(self, session_id: str) -> Iterable[Path]:
        del session_id
        if self.base_path is None:
            return ()
        return (self.base_path / "bad.jsonl", self.base_path / "good.jsonl")

    def _should_scan_file(self, file_path: Path, cutoff: datetime) -> bool:
        del cutoff
        if file_path.name == "bad.jsonl":
            raise ValueError("malformed session")
        return True

    def _parse_session_file(self, file_path: Path) -> Session | None:
        if file_path.name == "bad.jsonl":
            raise ValueError("malformed session")
        now = datetime.now(timezone.utc)
        return Session(
            id="target",
            title="Valid",
            created_at=now,
            updated_at=now,
            source_path=file_path,
            metadata={},
        )

    def get_session_data(self, session: Session) -> dict:
        del session
        return {}


def test_file_scan_reports_one_bad_file_and_keeps_valid_sessions(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.jsonl"
    good_path = tmp_path / "good.jsonl"
    bad_path.touch()
    good_path.touch()
    agent = FailingFileAgent(tmp_path)
    diagnostics: list[ProviderDiagnostic] = []

    results = AgentScanner([agent], diagnostic_sink=diagnostics.append).get_sessions(days=7)

    assert [(item.id, item.source_path) for item in results[0][1]] == [("target", good_path)]
    assert diagnostics == [
        ProviderDiagnostic(
            message_key=Keys.WARN_SESSION_PARSE_FAILED,
            fields={"path": str(bad_path), "error": "malformed session"},
        )
    ]


def test_available_file_sessions_reuse_one_file_discovery(tmp_path: Path) -> None:
    good_path = tmp_path / "good.jsonl"
    good_path.touch()
    agent = FailingFileAgent(tmp_path)

    results = AgentScanner([agent]).get_available_sessions(days=7)

    assert [(item.id, item.source_path) for item in results[0][1]] == [("target", good_path)]
    assert agent.file_discovery_count == 1


def test_file_lookup_reports_bad_candidate_and_continues(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.jsonl"
    good_path = tmp_path / "good.jsonl"
    bad_path.touch()
    good_path.touch()
    agent = FailingFileAgent(tmp_path)
    diagnostics: list[ProviderDiagnostic] = []

    result = AgentScanner([agent], diagnostic_sink=diagnostics.append).find_session_by_id(
        "target",
        agent_name=agent.name,
    )

    assert result is not None
    assert result[1].source_path == good_path
    assert diagnostics == [
        ProviderDiagnostic(
            message_key=Keys.WARN_SESSION_PARSE_FAILED,
            fields={"path": str(bad_path), "error": "malformed session"},
        )
    ]


def test_codex_scan_reports_structurally_invalid_session(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text('{"type":"session_meta","payload":"not-an-object"}\n', encoding="utf-8")
    agent = CodexAgent()
    agent.base_path = tmp_path
    diagnostics: list[ProviderDiagnostic] = []

    results = AgentScanner([agent], diagnostic_sink=diagnostics.append).get_sessions(days=7)

    assert results == [(agent, [])]
    assert len(diagnostics) == 1
    assert diagnostics[0].message_key == Keys.WARN_SESSION_PARSE_FAILED
    assert diagnostics[0].fields["path"] == str(bad_path)
    assert "has no attribute 'get'" in str(diagnostics[0].fields["error"])
