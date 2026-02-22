"""
Scanner for agent tools
"""

from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.agents.codex import CodexAgent
from agent_dump.agents.kimi import KimiAgent
from agent_dump.agents.claudecode import ClaudeCodeAgent


class AgentScanner:
    """Scanner for all supported agent tools"""

    def __init__(self):
        self.agents: list[BaseAgent] = [
            OpenCodeAgent(),
            CodexAgent(),
            KimiAgent(),
            ClaudeCodeAgent(),
        ]

    def scan(self) -> dict[str, list[Session]]:
        """
        Scan all agents and return available sessions.
        Returns a dict mapping agent name to list of sessions.
        """
        print("🔍 正在扫描 Agent Tools...\n")

        results: dict[str, list[Session]] = {}

        for agent in self.agents:
            if agent.is_available():
                sessions = agent.scan()
                if sessions:
                    results[agent.name] = sessions
                    print(f"   ✓ 发现 {agent.display_name} ({len(sessions)} 个会话)")
                else:
                    print(f"   ⚠ 发现 {agent.display_name} (0 个会话)")

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
