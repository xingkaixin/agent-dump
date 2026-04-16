"""URI parsing and session lookup helpers."""

import re
from concurrent.futures import ThreadPoolExecutor

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
    available_agents = scanner.get_available_agents()
    if not available_agents:
        return None

    # Fetch sessions concurrently to speed up URI resolution
    agent_sessions: list[tuple[BaseAgent, list[Session]]] = []
    with ThreadPoolExecutor(max_workers=len(available_agents)) as executor:
        futures = [executor.submit(agent.get_sessions, days=3650) for agent in available_agents]
        for i, future in enumerate(futures):
            try:
                sessions = future.result()
            except Exception:
                sessions = []
            agent_sessions.append((available_agents[i], sessions))

    for agent, sessions in agent_sessions:
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
