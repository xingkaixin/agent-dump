"""URI parsing and session lookup helpers."""

import re

from agent_dump.agent_registry import get_uri_path_prefixes, get_uri_scheme_map
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

    for prefix in get_uri_path_prefixes().get(scheme, ()):
        if session_id.startswith(prefix):
            session_id = session_id.removeprefix(prefix)
            if not session_id:
                return None
            break

    return scheme, session_id


def find_session_by_id(
    scanner: AgentScanner,
    session_id: str,
    *,
    agent_name: str | None = None,
) -> tuple[BaseAgent, Session] | None:
    """Compatibility adapter for Scanner-owned session lookup."""
    return scanner.find_session_by_id(session_id, agent_name=agent_name)
