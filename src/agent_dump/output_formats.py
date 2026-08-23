"""Output format definitions and validation."""

from collections.abc import Sequence
from typing import Literal, Protocol, TypeAlias

from agent_dump.diagnostics import unsupported_capability
from agent_dump.i18n import Keys, i18n

OutputFormat: TypeAlias = Literal["json", "markdown", "raw", "print"]
FileOutputFormat: TypeAlias = Literal["json", "markdown", "raw"]

VALID_FORMATS: frozenset[OutputFormat] = frozenset({"json", "markdown", "raw", "print"})
FORMAT_ALIASES: dict[str, OutputFormat] = {"md": "markdown"}


class UriFormatCapabilities(Protocol):
    display_name: str
    unsupported_uri_formats: frozenset[str]


def parse_format_spec(raw: str) -> list[OutputFormat]:
    formats: list[OutputFormat] = []
    seen: set[OutputFormat] = set()

    for part in raw.split(","):
        candidate = part.strip().lower()
        if not candidate:
            raise ValueError("empty format")
        normalized = FORMAT_ALIASES.get(candidate)
        if normalized is None:
            if candidate not in VALID_FORMATS:
                raise ValueError(candidate)
            normalized = candidate
        if normalized in seen:
            continue
        seen.add(normalized)
        formats.append(normalized)

    if not formats:
        raise ValueError("empty format")

    return formats


def file_output_formats(formats: Sequence[OutputFormat]) -> tuple[FileOutputFormat, ...]:
    return tuple(output_format for output_format in formats if output_format != "print")


def validate_formats_for_mode(formats: Sequence[OutputFormat], is_uri_mode: bool, is_list_mode: bool) -> None:
    if is_list_mode or is_uri_mode:
        return
    if "print" in formats:
        raise ValueError("interactive-print")


def validate_uri_agent_formats(agent: UriFormatCapabilities, formats: Sequence[OutputFormat]) -> None:
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
