"""
Scanner for agent tools
"""

from agent_dump.agent_registry import create_registered_agents
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.i18n import Keys, i18n


class AgentScanner:
    """Scanner for all supported agent tools"""

    def __init__(self):
        self.agents: list[BaseAgent] = create_registered_agents()

    def scan(self) -> dict[str, list[Session]]:
        """
        Scan all agents and return available sessions.
        Returns a dict mapping agent name to list of sessions.
        """
        print(i18n.t(Keys.SCANNING_AGENTS))

        results: dict[str, list[Session]] = {}

        for agent in self.agents:
            if agent.is_available():
                sessions = agent.scan()
                if sessions:
                    results[agent.name] = sessions
                    print(i18n.t(Keys.AGENT_FOUND, name=agent.display_name, count=len(sessions)))
                else:
                    print(i18n.t(Keys.AGENT_FOUND_EMPTY, name=agent.display_name))

        print()
        return results

    def get_available_agents(self) -> list[BaseAgent]:
        """Get list of available agents with sessions"""
        return [agent for agent in self.agents if agent.is_available()]

    def get_agent_by_name(self, name: str) -> BaseAgent | None:
        """Get agent by name"""
        for agent in self.agents:
            if agent.name == name:
                return agent if agent.is_available() else None
        return None
