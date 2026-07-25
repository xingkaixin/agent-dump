"""
Scanner for agent tools
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
import sys
from typing import TypeVar

from agent_dump.agent_registry import create_registered_agents
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.i18n import Keys, i18n

T = TypeVar("T")


def run_per_agent(fn: Callable[[BaseAgent], T], agents: Sequence[BaseAgent]) -> list[tuple[BaseAgent, T | None]]:
    """Run fn for every agent concurrently, isolating per-provider failures.

    一个 provider 抛异常只让它自己的结果变成 None 并向 stderr 告警，其余 provider
    照常返回。结果顺序与传入顺序一致。
    """
    if not agents:
        return []

    with ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = [executor.submit(fn, agent) for agent in agents]
        results: list[tuple[BaseAgent, T | None]] = []
        for agent, future in zip(agents, futures, strict=True):
            try:
                result = future.result()
            except Exception as exc:
                print(
                    f"警告: {agent.display_name} provider 操作失败: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                result = None
            results.append((agent, result))
        return results


def sessions_per_agent(agents: Sequence[BaseAgent], days: int) -> list[tuple[BaseAgent, list[Session]]]:
    """Fetch each agent's sessions, degrading a failed provider to an empty list.

    裸 `agent.get_sessions()` 循环会让一个 provider 的坏数据崩掉整条命令；这里把
    失败收敛成「该 provider 没有会话」，其余 provider 的结果仍然可用。
    """
    return [(agent, sessions or []) for agent, sessions in run_per_agent(lambda a: a.get_sessions(days=days), agents)]


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
        self, fn: Callable[[BaseAgent], T], agents: Sequence[BaseAgent] | None = None
    ) -> list[tuple[BaseAgent, T | None]]:
        """Execute a function for all agents concurrently and return results in registration order."""
        return run_per_agent(fn, agents if agents is not None else self.agents)

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
