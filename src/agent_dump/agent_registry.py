"""Central registry for supported agent integrations."""

from collections.abc import Callable
from dataclasses import dataclass

from agent_dump.agents.base import BaseAgent
from agent_dump.agents.claudecode import ClaudeCodeAgent
from agent_dump.agents.codex import CodexAgent
from agent_dump.agents.cursor import CursorAgent
from agent_dump.agents.kimi import KimiAgent
from agent_dump.agents.opencode import OpenCodeAgent


@dataclass(frozen=True)
class AgentRegistration:
    """One supported agent integration."""

    name: str
    display_name: str
    factory: Callable[[], BaseAgent]
    uri_schemes: tuple[str, ...]
    location_line: str


AGENT_REGISTRATIONS: tuple[AgentRegistration, ...] = (
    AgentRegistration(
        name="opencode",
        display_name="OpenCode",
        factory=OpenCodeAgent,
        uri_schemes=("opencode",),
        location_line="  - OpenCode: XDG_DATA_HOME/opencode/opencode.db or ~/.local/share/opencode/opencode.db",
    ),
    AgentRegistration(
        name="codex",
        display_name="Codex",
        factory=CodexAgent,
        uri_schemes=("codex",),
        location_line="  - Codex: CODEX_HOME/sessions or ~/.codex/sessions",
    ),
    AgentRegistration(
        name="kimi",
        display_name="Kimi",
        factory=KimiAgent,
        uri_schemes=("kimi",),
        location_line="  - Kimi: KIMI_SHARE_DIR/sessions or ~/.kimi/sessions",
    ),
    AgentRegistration(
        name="claudecode",
        display_name="Claude Code",
        factory=ClaudeCodeAgent,
        uri_schemes=("claude",),
        location_line="  - Claude Code: CLAUDE_CONFIG_DIR/projects or ~/.claude/projects",
    ),
    AgentRegistration(
        name="cursor",
        display_name="Cursor",
        factory=CursorAgent,
        uri_schemes=("cursor",),
        location_line="  - Cursor: CURSOR_DATA_PATH or ~/Library/Application Support/Cursor/User/*",
    ),
)


def create_registered_agents() -> list[BaseAgent]:
    """Instantiate all registered agents."""
    return [registration.factory() for registration in AGENT_REGISTRATIONS]


def get_uri_scheme_map() -> dict[str, str]:
    """Return supported URI scheme to agent name mapping."""
    return {
        scheme: registration.name
        for registration in AGENT_REGISTRATIONS
        for scheme in registration.uri_schemes
    }


def get_supported_agent_locations() -> list[str]:
    """Return storage location help text for all supported agents."""
    lines = [registration.location_line for registration in AGENT_REGISTRATIONS]
    lines.append("  - Local development fallback: data/opencode, data/codex, data/kimi, data/claudecode")
    return lines


def get_supported_uri_examples() -> list[str]:
    """Return user-facing URI examples."""
    examples = [f"  - {scheme}://<session_id>" for scheme in get_uri_scheme_map()]
    examples.insert(2, "  - codex://threads/<session_id>")
    examples[-1] = "  - cursor://<requestid>"
    return examples
