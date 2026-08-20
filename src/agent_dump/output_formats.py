"""Output format definitions and validation."""

from agent_dump.agents.base import BaseAgent
from agent_dump.diagnostics import unsupported_capability
from agent_dump.i18n import Keys, i18n

VALID_FORMATS = {"json", "markdown", "raw", "print"}
FORMAT_ALIASES = {"md": "markdown"}


def parse_format_spec(raw: str) -> list[str]:
    formats: list[str] = []
    seen: set[str] = set()

    for part in raw.split(","):
        candidate = part.strip().lower()
        normalized = FORMAT_ALIASES.get(candidate, candidate)
        if not normalized:
            raise ValueError("empty format")
        if normalized not in VALID_FORMATS:
            raise ValueError(normalized)
        if normalized in seen:
            continue
        seen.add(normalized)
        formats.append(normalized)

    if not formats:
        raise ValueError("empty format")

    return formats


def validate_formats_for_mode(formats: list[str], is_uri_mode: bool, is_list_mode: bool) -> None:
    if is_list_mode or is_uri_mode:
        return
    if "print" in formats:
        raise ValueError("interactive-print")


def validate_uri_agent_formats(agent: BaseAgent, formats: list[str]) -> None:
    unsupported = [output_format for output_format in formats if output_format in agent.unsupported_uri_formats]
    if not unsupported:
        return

    requested = ",".join(unsupported)
    supported = ", ".join(sorted(VALID_FORMATS - agent.unsupported_uri_formats))
    raise unsupported_capability(
        i18n.t(Keys.DIAG_URI_CAPABILITY_GAP, agent=agent.display_name),
        capability_gap=i18n.t(
            Keys.DIAG_URI_CAPABILITY_DETAIL,
            agent=agent.display_name,
            supported=supported,
            requested=requested,
        ),
        next_steps=(
            i18n.t(Keys.DIAG_STEP_DROP_FORMATS, formats=", ".join(f"`{item}`" for item in unsupported)),
            i18n.t(Keys.DIAG_STEP_EXPORT_JSON_FIRST),
        ),
    )
