"""
Scanner for agent tools
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from agent_dump.agent_registry import create_registered_agents
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.i18n import Keys, i18n
from agent_dump.provider_diagnostics import ProviderDiagnostic, ProviderDiagnosticSink, print_provider_diagnostic
from agent_dump.terminal_output import render_terminal_message

T = TypeVar("T")


class AgentScanner:
    """Scanner for all supported agent tools"""

    def __init__(
        self,
        agents: Sequence[BaseAgent] | None = None,
        *,
        diagnostic_sink: ProviderDiagnosticSink | None = print_provider_diagnostic,
    ) -> None:
        self.agents = list(agents) if agents is not None else create_registered_agents()
        self._diagnostic_sink = diagnostic_sink
        for agent in self.agents:
            agent._set_diagnostic_sink(diagnostic_sink)

    @staticmethod
    def _operation_failure_diagnostic(agent: BaseAgent, exc: Exception) -> ProviderDiagnostic:
        return ProviderDiagnostic(
            message_key=Keys.WARN_PROVIDER_OPERATION_FAILED,
            fields={
                "agent": agent.display_name,
                "error_type": type(exc).__name__,
                "error": exc,
            },
        )

    @staticmethod
    def _lookup_failure_diagnostic(agent: BaseAgent, exc: Exception) -> ProviderDiagnostic:
        return ProviderDiagnostic(
            message_key=Keys.WARN_SESSION_LOOKUP_FAILED,
            fields={"agent": agent.display_name, "error": exc},
        )

    @staticmethod
    def _scan_single_agent(agent: BaseAgent) -> list[Session] | None:
        """Check availability and scan one agent."""
        if agent.is_available():
            return agent.scan()
        return None

    def _run_concurrently(
        self,
        fn: Callable[[BaseAgent], T],
        agents: Sequence[BaseAgent] | None = None,
        *,
        diagnostic_factory: Callable[[BaseAgent, Exception], ProviderDiagnostic] | None = None,
    ) -> list[tuple[BaseAgent, T | None]]:
        """Execute one provider operation concurrently in registration order."""
        selected_agents = list(agents) if agents is not None else self.agents
        if not selected_agents:
            return []

        with ThreadPoolExecutor(max_workers=len(selected_agents)) as executor:
            futures = [executor.submit(fn, agent) for agent in selected_agents]
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
        """
        Scan all agents concurrently and return available sessions.
        Returns a dict mapping agent name to list of sessions.
        """
        print(i18n.t(Keys.SCANNING_AGENTS))

        results: dict[str, list[Session]] = {}
        agent_results = self._run_concurrently(self._scan_single_agent)

        for agent, sessions in agent_results:
            if sessions is not None:
                if sessions:
                    results[agent.name] = sessions
                    print(render_terminal_message(Keys.AGENT_FOUND, name=agent.display_name, count=len(sessions)))
                else:
                    print(render_terminal_message(Keys.AGENT_FOUND_EMPTY, name=agent.display_name))

        print()
        return results

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
                return agent if agent.is_available() else None
        return None
