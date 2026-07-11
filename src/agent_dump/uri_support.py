"""URI parsing and session lookup helpers."""

import re
import sys

from agent_dump.agent_registry import get_uri_scheme_map
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.scanner import AgentScanner


def parse_uri(uri: str) -> tuple[str, str] | None:
    """Parse an agent session URI."""
    match = re.match(r"^([a-z]+)://(.+)$", uri)
    if not match:
        return None

    scheme, session_id = match.groups()
    if scheme not in get_uri_scheme_map():
        return None

    if scheme == "codex" and session_id.startswith("threads/"):
        session_id = session_id.removeprefix("threads/")
        if not session_id:
            return None

    return scheme, session_id


def find_session_by_id(
    scanner: AgentScanner,
    session_id: str,
    *,
    agent_name: str | None = None,
) -> tuple[BaseAgent, Session] | None:
    """Find a session by ID via provider-level lookups."""
    available_agents = scanner.get_available_agents()
    if agent_name is not None:
        available_agents = [agent for agent in available_agents if agent.name == agent_name]

    for agent in available_agents:
        try:
            session = agent.find_session_by_id(session_id)
        except Exception as exc:
            print(f"警告: {agent.display_name} 查找会话失败: {exc}", file=sys.stderr)
            continue
        if session is not None:
            return agent, session

    return None
