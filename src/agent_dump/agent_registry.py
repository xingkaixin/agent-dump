"""Central registry for supported agent integrations."""

from dataclasses import dataclass

from agent_dump.agents.base import BaseAgent
from agent_dump.agents.claudecode import ClaudeCodeAgent
from agent_dump.agents.codex import CodexAgent
from agent_dump.agents.cursor import CursorAgent
from agent_dump.agents.kimi import KimiAgent
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.agents.pi import PiAgent
from agent_dump.agents.zcode import ZCodeAgent


@dataclass(frozen=True)
class AgentRegistration:
    """One supported agent integration."""

    factory: type[BaseAgent]
    uri_schemes: tuple[str, ...]
    location_line: str
    # 该 provider 额外接受的 URI 路径前缀，如 codex 的 `codex://threads/<id>`。
    # 之前这个形状硬编码在 uri_support.parse_uri 与 get_supported_uri_examples 里，
    # 违反「provider schema 只在对应 Agent 内处理」，也让 registry 不是它被文档化的单一真源。
    uri_path_prefixes: tuple[str, ...] = ()
    # URI 示例里 session id 占位符的写法；Cursor 用的是 bubble 级的 requestId。
    uri_identifier_label: str = "<session_id>"

    @property
    def name(self) -> str:
        return self.factory.provider_name

    @property
    def display_name(self) -> str:
        return self.factory.provider_display_name


AGENT_REGISTRATIONS: tuple[AgentRegistration, ...] = (
    AgentRegistration(
        factory=OpenCodeAgent,
        uri_schemes=("opencode",),
        location_line="  - OpenCode: XDG_DATA_HOME/opencode/opencode.db or ~/.local/share/opencode/opencode.db",
    ),
    AgentRegistration(
        factory=ZCodeAgent,
        uri_schemes=("zcode",),
        location_line="  - ZCode: ~/.zcode/cli/db/db.sqlite on macOS or %USERPROFILE%\\.zcode\\cli\\db\\db.sqlite on Windows",
    ),
    AgentRegistration(
        factory=CodexAgent,
        uri_schemes=("codex",),
        uri_path_prefixes=("threads/",),
        location_line="  - Codex: CODEX_HOME/sessions or ~/.codex/sessions",
    ),
    AgentRegistration(
        factory=KimiAgent,
        uri_schemes=("kimi",),
        location_line="  - Kimi: KIMI_SHARE_DIR/sessions or ~/.kimi/sessions",
    ),
    AgentRegistration(
        factory=ClaudeCodeAgent,
        uri_schemes=("claude",),
        location_line="  - Claude Code: CLAUDE_CONFIG_DIR/projects or ~/.claude/projects",
    ),
    AgentRegistration(
        factory=CursorAgent,
        uri_schemes=("cursor",),
        uri_identifier_label="<requestid>",
        location_line="  - Cursor: ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb",
    ),
    AgentRegistration(
        factory=PiAgent,
        uri_schemes=("pi",),
        location_line="  - Pi: PI_HOME/agent/sessions or ~/.pi/agent/sessions",
    ),
)


def create_registered_agents() -> list[BaseAgent]:
    """Instantiate all registered agents."""
    return [registration.factory() for registration in AGENT_REGISTRATIONS]


def get_uri_scheme_map() -> dict[str, str]:
    """Return supported URI scheme to agent name mapping."""
    return {scheme: registration.name for registration in AGENT_REGISTRATIONS for scheme in registration.uri_schemes}


def get_supported_agent_locations() -> list[str]:
    """Return storage location help text for all supported agents."""
    lines = [registration.location_line for registration in AGENT_REGISTRATIONS]
    lines.append("  - Local development fallback: data/opencode, data/codex, data/kimi, data/claudecode, data/pi")
    return lines


def get_uri_path_prefixes() -> dict[str, tuple[str, ...]]:
    """Return scheme to accepted URI path prefixes mapping."""
    return {
        scheme: registration.uri_path_prefixes
        for registration in AGENT_REGISTRATIONS
        for scheme in registration.uri_schemes
    }


def get_supported_uri_examples() -> list[str]:
    """Return user-facing URI examples, driven entirely by the registry."""
    examples = []
    for registration in AGENT_REGISTRATIONS:
        for scheme in registration.uri_schemes:
            examples.append(f"  - {scheme}://{registration.uri_identifier_label}")
            examples.extend(
                f"  - {scheme}://{prefix}{registration.uri_identifier_label}"
                for prefix in registration.uri_path_prefixes
            )
    return examples
