from collections.abc import Collection, Sequence
from pathlib import Path

from agent_dump.agent_registry import get_supported_agent_locations
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import (
    DiagnosticError,
    invalid_query_or_uri,
    print_recoverable_diagnostic,
    render_diagnostic,
    root_not_found,
)
from agent_dump.i18n import Keys, i18n
from agent_dump.output_formats import FileOutputFormat, OutputFormat
from agent_dump.query_filter import (
    QuerySpec,
    select_session_groups,
)
from agent_dump.scanner import AgentScanner

DEFAULT_OUTPUT_BASE_DIR = Path("./sessions")


def uses_configured_export_output(
    *,
    output_specified: bool,
    output_formats: Collection[OutputFormat],
) -> bool:
    return not output_specified and any(output_format in {"json", "raw"} for output_format in output_formats)


def resolve_output_base_dir(
    *,
    cli_output: str | None,
    output_specified: bool,
    export_output: str,
    output_format: FileOutputFormat,
) -> Path:
    if output_specified and cli_output:
        return Path(cli_output)
    if (
        uses_configured_export_output(
            output_specified=output_specified,
            output_formats=(output_format,),
        )
        and export_output
    ):
        return Path(export_output)
    return DEFAULT_OUTPUT_BASE_DIR


def discover_query_sessions(
    scanner: AgentScanner,
    days: int | None,
    spec: QuerySpec | None,
) -> list[tuple[BaseAgent, list[Session]]]:
    """Apply an explicit provider scope before starting discovery."""
    if spec is None or spec.agent_names is None:
        return scanner.get_available_sessions(days)
    agents = [agent for agent in scanner.agents if agent.name in spec.agent_names]
    return scanner.get_available_sessions(days, agents=agents)


def collect_query_matches(
    session_groups: Sequence[tuple[BaseAgent, list[Session]]],
    *,
    spec: QuerySpec,
) -> dict[str, list[Session]]:
    grouped: dict[str, list[Session]] = {}
    for match in select_session_groups(session_groups, spec, diagnostic_sink=print_recoverable_diagnostic):
        grouped.setdefault(match.agent.name, []).append(match.session)
    return grouped


def render_agent_search_roots(agents: Sequence[BaseAgent]) -> tuple[str, ...]:
    roots: list[str] = []
    for agent in agents:
        provider_roots = [root.render() for root in agent.get_search_roots()]
        if not provider_roots:
            continue
        roots.extend(f"{agent.display_name}: {entry}" for entry in provider_roots)
    return tuple(roots)


def print_diagnostic(error: DiagnosticError) -> None:
    print(render_diagnostic(error, t=i18n.t))


def build_no_agents_found_diagnostic(scanner: AgentScanner) -> DiagnosticError:
    searched_roots = render_agent_search_roots(scanner.agents)
    if not searched_roots:
        searched_roots = tuple(location.strip() for location in get_supported_agent_locations())
    return root_not_found(
        i18n.t(Keys.DIAG_NO_LOCAL_SESSIONS),
        searched_roots=searched_roots,
        next_steps=(
            i18n.t(Keys.DIAG_STEP_CHECK_AGENT_DATA),
            i18n.t(Keys.DIAG_STEP_CHECK_ENV_VARS),
            i18n.t(Keys.DIAG_STEP_CHECK_DEV_FALLBACK),
        ),
    )


def scope_session_groups_by_provider(
    session_groups: Sequence[tuple[BaseAgent, list[Session]]],
    *,
    agent_names: Collection[str] | None,
    all_agents: Sequence[BaseAgent],
) -> tuple[list[tuple[BaseAgent, list[Session]]], DiagnosticError | None]:
    if not agent_names:
        return list(session_groups), None

    scoped_groups = [(agent, sessions) for agent, sessions in session_groups if agent.name in agent_names]
    if scoped_groups:
        return scoped_groups, None

    return [], root_not_found(
        i18n.t(Keys.DIAG_NO_PROVIDER_IN_SCOPE),
        searched_roots=render_agent_search_roots(all_agents),
        details=(f"query providers: {','.join(sorted(agent_names))}",),
        next_steps=(
            i18n.t(Keys.DIAG_STEP_CONFIRM_PROVIDERS_HAVE_DATA),
            i18n.t(Keys.DIAG_STEP_WIDEN_PROVIDERS),
        ),
    )


def _runtime_fetch_next_steps() -> tuple[str, ...]:
    return (
        i18n.t(Keys.DIAG_STEP_CHECK_LOCAL_SOURCE),
        i18n.t(Keys.DIAG_STEP_NARROW_WITH_LIST),
    )


def wrap_runtime_fetch_error(exc: Exception, *, agent: BaseAgent | None = None) -> DiagnosticError:
    searched_roots = render_agent_search_roots([agent]) if agent is not None else ()
    return (
        invalid_query_or_uri(
            i18n.t(Keys.DIAG_SESSION_READ_FAILED),
            details=(str(exc),),
            next_steps=_runtime_fetch_next_steps(),
        )
        if not searched_roots
        else root_not_found(
            i18n.t(Keys.DIAG_SESSION_READ_FAILED),
            details=(str(exc),),
            searched_roots=searched_roots,
            next_steps=_runtime_fetch_next_steps(),
        )
    )
