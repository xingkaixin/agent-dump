"""
Scanner for agent tools
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from agent_dump.agent_registry import create_registered_agents
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.i18n import Keys, i18n

T = TypeVar("T")


class AgentScanner:
    """Scanner for all supported agent tools"""

    def __init__(self):
        self.agents: list[BaseAgent] = create_registered_agents()

    @staticmethod
    def _scan_single_agent(agent: BaseAgent) -> list[Session] | None:
        """Check availability and scan one agent."""
        if agent.is_available():
            return agent.scan()
        return None

    def _run_concurrently(
        self, fn: Callable[[BaseAgent], T], agents: list[BaseAgent] | None = None
    ) -> list[tuple[BaseAgent, T]]:
        """Execute a function for all agents concurrently and return results in registration order."""
        targets = agents if agents is not None else self.agents
        with ThreadPoolExecutor(max_workers=len(targets)) as executor:
            futures = [executor.submit(fn, agent) for agent in targets]
            return [(targets[i], future.result()) for i, future in enumerate(futures)]

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
                    print(i18n.t(Keys.AGENT_FOUND, name=agent.display_name, count=len(sessions)))
                else:
                    print(i18n.t(Keys.AGENT_FOUND_EMPTY, name=agent.display_name))

        print()
        return results

    def get_available_agents(self) -> list[BaseAgent]:
        """Get list of available agents with sessions"""
        results = self._run_concurrently(lambda agent: agent.is_available())
        return [agent for agent, available in results if available]

    def get_agent_by_name(self, name: str) -> BaseAgent | None:
        """Get agent by name"""
        for agent in self.agents:
            if agent.name == name:
                return agent if agent.is_available() else None
        return None
