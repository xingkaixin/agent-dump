"""
Scanner for agent tools
"""

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from typing import TypeVar

from agent_dump.agent_registry import create_registered_agents
from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.diagnostics import RecoverableDiagnostic, RecoverableDiagnosticSink, print_recoverable_diagnostic
from agent_dump.i18n import Keys

T = TypeVar("T")


class AgentScanner:
    """Scanner for all supported agent tools"""

    def __init__(
        self,
        agents: Sequence[BaseAgent] | None = None,
        *,
        diagnostic_sink: RecoverableDiagnosticSink | None = print_recoverable_diagnostic,
    ) -> None:
        self.agents = list(agents) if agents is not None else create_registered_agents()
        self._diagnostic_sink = diagnostic_sink

    @contextmanager
    def diagnostic_context(self) -> Iterator[None]:
        """Keep this caller's diagnostics active while consuming discovered sessions."""
        with ExitStack() as stack:
            for agent in self.agents:
                stack.enter_context(agent.diagnostic_context(self._diagnostic_sink))
            yield

    @staticmethod
    def _operation_failure_diagnostic(agent: BaseAgent, exc: Exception) -> RecoverableDiagnostic:
        return RecoverableDiagnostic(
            message_key=Keys.WARN_PROVIDER_OPERATION_FAILED,
            fields={
                "agent": agent.display_name,
                "error_type": type(exc).__name__,
                "error": exc,
            },
        )

    @staticmethod
    def _lookup_failure_diagnostic(agent: BaseAgent, exc: Exception) -> RecoverableDiagnostic:
        return RecoverableDiagnostic(
            message_key=Keys.WARN_SESSION_LOOKUP_FAILED,
            fields={"agent": agent.display_name, "error": exc},
        )

    def _run_concurrently(
        self,
        fn: Callable[[BaseAgent], T],
        agents: Sequence[BaseAgent] | None = None,
        *,
        diagnostic_factory: Callable[[BaseAgent, Exception], RecoverableDiagnostic] | None = None,
    ) -> list[tuple[BaseAgent, T | None]]:
        """Execute one provider operation concurrently in registration order."""
        selected_agents = list(agents) if agents is not None else self.agents
        if not selected_agents:
            return []

        def run_for_scanner(agent: BaseAgent) -> T:
            with agent.diagnostic_context(self._diagnostic_sink):
                return fn(agent)

        with ThreadPoolExecutor(max_workers=len(selected_agents)) as executor:
            futures = [executor.submit(run_for_scanner, agent) for agent in selected_agents]
            results: list[tuple[BaseAgent, T | None]] = []
            for agent, future in zip(selected_agents, futures, strict=True):
                try:
                    result = future.result()
                except Exception as exc:
                    if self._diagnostic_sink is not None:
                        factory = diagnostic_factory or self._operation_failure_diagnostic
                        self._diagnostic_sink(factory(agent, exc))
                    result = None
                results.append((agent, result))
            return results

    def scan(self) -> dict[str, list[Session]]:
        """Scan all available providers and return their non-empty sessions."""
        return {agent.name: sessions for agent, sessions in self.get_available_sessions(days=None) if sessions}

    def get_available_agents(self) -> list[BaseAgent]:
        """Get list of available agents with sessions"""
        results = self._run_concurrently(lambda agent: agent.is_available())
        return [agent for agent, available in results if available]

    def get_sessions(
        self,
        days: int = 7,
        *,
        agents: Sequence[BaseAgent] | None = None,
    ) -> list[tuple[BaseAgent, list[Session]]]:
        """List sessions concurrently, degrading a failed provider to an empty result."""
        return [
            (agent, sessions or [])
            for agent, sessions in self._run_concurrently(
                lambda selected: selected.get_sessions(days=days),
                agents,
            )
        ]

    def get_available_sessions(
        self,
        days: int | None = 7,
        *,
        agents: Sequence[BaseAgent] | None = None,
    ) -> list[tuple[BaseAgent, list[Session]]]:
        """Read availability and sessions together without probing providers twice."""
        discoveries: list[tuple[BaseAgent, ProviderDiscovery | None]] = self._run_concurrently(
            lambda agent: agent.discover_sessions(days),
            agents,
        )
        return [
            (agent, list(discovery.sessions))
            for agent, discovery in discoveries
            if discovery is not None and discovery.available
        ]

    def find_session_by_id(
        self,
        session_id: str,
        *,
        agent_name: str | None = None,
    ) -> tuple[BaseAgent, Session] | None:
        """Locate a session across providers with per-provider failure isolation."""
        candidates = [agent for agent in self.agents if agent_name is None or agent.name == agent_name]
        results = self._run_concurrently(
            lambda agent: agent.find_session_by_id(session_id),
            candidates,
            diagnostic_factory=self._lookup_failure_diagnostic,
        )
        return next(
            ((agent, session) for agent, session in results if session is not None),
            None,
        )

    def get_agent_by_name(self, name: str) -> BaseAgent | None:
        """Get agent by name"""
        for agent in self.agents:
            if agent.name == name:
                with agent.diagnostic_context(self._diagnostic_sink):
                    return agent if agent.is_available() else None
        return None
