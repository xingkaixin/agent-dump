"""URI parsing and session lookup helpers."""

import re

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


def find_session_by_id(scanner: AgentScanner, session_id: str) -> tuple[BaseAgent, Session] | None:
    """Find a session by ID across all available agents."""
    for agent in scanner.get_available_agents():
        sessions = agent.get_sessions(days=3650)
        for session in sessions:
            if session.id == session_id:
                return agent, session
            if agent.name == "cursor" and session.metadata.get("request_id") == session_id:
                return agent, session

        if agent.name != "cursor":
            continue

        finder = getattr(agent, "find_session_by_request_id", None)
        if not callable(finder):
            continue

        matched_session = finder(session_id)
        if isinstance(matched_session, Session):
            return agent, matched_session

    return None
