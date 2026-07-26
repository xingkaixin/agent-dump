"""Scanner module tests."""

from datetime import datetime, timezone
from pathlib import Path
import threading

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.scanner import AgentScanner, sessions_per_agent


def make_session(session_id: str) -> Session:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Session(
        id=session_id,
        title=session_id,
        created_at=timestamp,
        updated_at=timestamp,
        source_path=Path(f"/tmp/{session_id}.jsonl"),
        metadata={},
    )


class FakeAgent(BaseAgent):
    def __init__(
        self,
        name: str,
        *,
        available: bool = True,
        sessions: tuple[Session, ...] = (),
        lookup: Session | None = None,
    ):
        super().__init__(name, name.title())
        self.available = available
        self.sessions = sessions
        self.lookup = lookup
        self.availability_error: Exception | None = None
        self.scan_error: Exception | None = None
        self.sessions_error: Exception | None = None
        self.lookup_error: Exception | None = None
        self.scan_barrier: threading.Barrier | None = None
        self.sessions_barrier: threading.Barrier | None = None
        self.lookup_barrier: threading.Barrier | None = None

    def scan(self) -> list[Session]:
        if self.scan_error is not None:
            raise self.scan_error
        if self.scan_barrier is not None:
            self.scan_barrier.wait()
        return list(self.sessions)

    def is_available(self) -> bool:
        if self.availability_error is not None:
            raise self.availability_error
        return self.available

    def get_sessions(self, days: int = 7) -> list[Session]:
        del days
        if self.sessions_error is not None:
            raise self.sessions_error
        if self.sessions_barrier is not None:
            self.sessions_barrier.wait()
        return list(self.sessions)

    def find_session_by_id(self, session_id: str) -> Session | None:
        del session_id
        if self.lookup_error is not None:
            raise self.lookup_error
        if self.lookup_barrier is not None:
            self.lookup_barrier.wait()
        return self.lookup

    def get_session_data(self, session: Session) -> dict:
        del session
        return {}


class TestAgentScanner:
    def test_default_init_creates_registered_agents(self):
        scanner = AgentScanner()

        assert [agent.name for agent in scanner.agents] == [
            "opencode",
            "zcode",
            "codex",
            "kimi",
            "claudecode",
            "cursor",
            "pi",
        ]

    def test_accepts_injected_agents(self):
        agents = [FakeAgent("one"), FakeAgent("two")]

        assert AgentScanner(agents).agents == agents

    def test_scan_reports_available_and_empty_agents(self, capsys):
        session = make_session("one-session")
        scanner = AgentScanner(
            [
                FakeAgent("one", sessions=(session,)),
                FakeAgent("empty"),
                FakeAgent("missing", available=False),
            ]
        )

        result = scanner.scan()

        assert result == {"one": [session]}
        output = capsys.readouterr().out
        assert "One" in output
        assert "1 个会话" in output
        assert "Empty" in output
        assert "0 个会话" in output
        assert "Missing" not in output

    @pytest.mark.parametrize(
        ("failure_stage", "error"),
        [
            ("availability", PermissionError("permission denied")),
            ("scan", RuntimeError("database is corrupt")),
        ],
    )
    def test_scan_isolates_provider_failures(self, failure_stage, error, capsys):
        broken = FakeAgent("broken")
        healthy_session = make_session("healthy-session")
        healthy = FakeAgent("healthy", sessions=(healthy_session,))
        if failure_stage == "availability":
            broken.availability_error = error
        else:
            broken.scan_error = error

        result = AgentScanner([broken, healthy]).scan()

        assert result == {"healthy": [healthy_session]}
        warning = capsys.readouterr().err
        assert warning.count("Broken") == 1
        assert f"{type(error).__name__}: {error}" in warning

    def test_scan_runs_concurrently(self):
        barrier = threading.Barrier(2, timeout=10)
        agents = [
            FakeAgent("one", sessions=(make_session("one"),)),
            FakeAgent("two", sessions=(make_session("two"),)),
        ]
        for agent in agents:
            agent.scan_barrier = barrier

        result = AgentScanner(agents).scan()

        assert list(result) == ["one", "two"]

    def test_get_available_agents_preserves_order_and_isolates_failures(self, capsys):
        first = FakeAgent("first")
        broken = FakeAgent("broken")
        broken.availability_error = OSError("unreadable directory")
        unavailable = FakeAgent("unavailable", available=False)
        last = FakeAgent("last")

        available = AgentScanner([first, broken, unavailable, last]).get_available_agents()

        assert available == [first, last]
        assert "OSError: unreadable directory" in capsys.readouterr().err

    def test_get_sessions_runs_concurrently_and_preserves_order(self):
        barrier = threading.Barrier(2, timeout=10)
        first = FakeAgent("first", sessions=(make_session("first-session"),))
        second = FakeAgent("second", sessions=(make_session("second-session"),))
        first.sessions_barrier = barrier
        second.sessions_barrier = barrier

        results = AgentScanner([first, second]).get_sessions(days=7)

        assert [(agent.name, sessions[0].id) for agent, sessions in results] == [
            ("first", "first-session"),
            ("second", "second-session"),
        ]

    def test_get_sessions_isolates_provider_failures(self, capsys):
        healthy = FakeAgent("healthy", sessions=(make_session("healthy-session"),))
        broken = FakeAgent("broken")
        broken.sessions_error = ValueError("malformed row")

        results = AgentScanner([healthy, broken]).get_sessions(days=7)

        assert [(agent.name, [session.id for session in sessions]) for agent, sessions in results] == [
            ("healthy", ["healthy-session"]),
            ("broken", []),
        ]
        assert "ValueError: malformed row" in capsys.readouterr().err

    def test_find_session_runs_concurrently_and_uses_registration_order(self):
        barrier = threading.Barrier(2, timeout=10)
        first_session = make_session("first")
        second_session = make_session("second")
        first = FakeAgent("first", lookup=first_session)
        second = FakeAgent("second", lookup=second_session)
        first.lookup_barrier = barrier
        second.lookup_barrier = barrier

        result = AgentScanner([first, second]).find_session_by_id("target")

        assert result == (first, first_session)

    def test_find_session_filters_provider_and_isolates_failures(self, capsys):
        skipped = FakeAgent("skipped", lookup=make_session("wrong"))
        broken = FakeAgent("target")
        broken.lookup_error = RuntimeError("corrupt lookup")
        healthy_session = make_session("found")
        healthy = FakeAgent("target", lookup=healthy_session)

        result = AgentScanner([skipped, broken, healthy]).find_session_by_id(
            "found",
            agent_name="target",
        )

        assert result == (healthy, healthy_session)
        warning = capsys.readouterr().err
        assert "Target" in warning
        assert "corrupt lookup" in warning

    @pytest.mark.parametrize(
        ("name", "available", "found"),
        [
            ("one", True, True),
            ("one", False, False),
            ("missing", True, False),
        ],
    )
    def test_get_agent_by_name(self, name, available, found):
        agent = FakeAgent("one", available=available)

        result = AgentScanner([agent]).get_agent_by_name(name)

        assert (result is agent) is found


class TestSessionsPerAgentCompatibility:
    def test_delegates_to_scanner_semantics(self, capsys):
        first = FakeAgent("first", sessions=(make_session("first"),))
        broken = FakeAgent("broken")
        broken.sessions_error = ValueError("malformed row")

        results = sessions_per_agent([first, broken], days=7)

        assert [(agent.name, len(sessions)) for agent, sessions in results] == [
            ("first", 1),
            ("broken", 0),
        ]
        assert "ValueError" in capsys.readouterr().err

    def test_empty_agent_list(self):
        assert sessions_per_agent([], days=7) == []
