from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import sys
import threading

from agent_dump.agent_registry import get_supported_agent_locations
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import (
    DiagnosticError,
    invalid_query_or_uri,
    render_diagnostic,
    root_not_found,
)
from agent_dump.exporting import ExportRunResult, execute_exports
from agent_dump.i18n import Keys, i18n
from agent_dump.query_filter import (
    QuerySpec,
    SearchSessionMatch,
    filter_sessions,
    filter_sessions_by_query,
    limit_query_session_matches,
    limit_search_matches,
    query_session_matches,
    search_sessions_by_query,
)
from agent_dump.rendering import format_session_metadata_summary
from agent_dump.scanner import AgentScanner
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import safe_display_text
from agent_dump.time_utils import get_local_timezone, to_local_datetime

DEFAULT_OUTPUT_BASE_DIR = Path("./sessions")


def group_sessions_by_time(sessions: list[Session]) -> dict[str, list[Session]]:
    groups: dict[str, list[Session]] = {
        i18n.t(Keys.TIME_TODAY): [],
        i18n.t(Keys.TIME_YESTERDAY): [],
        i18n.t(Keys.TIME_THIS_WEEK): [],
        i18n.t(Keys.TIME_THIS_MONTH): [],
        i18n.t(Keys.TIME_OLDER): [],
    }

    key_today = i18n.t(Keys.TIME_TODAY)
    key_yesterday = i18n.t(Keys.TIME_YESTERDAY)
    key_week = i18n.t(Keys.TIME_THIS_WEEK)
    key_month = i18n.t(Keys.TIME_THIS_MONTH)
    key_older = i18n.t(Keys.TIME_OLDER)

    local_tz = get_local_timezone()
    now = datetime.now(local_tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    for session in sessions:
        session_time = to_local_datetime(session.created_at, local_tz)

        if session_time >= today:
            groups[key_today].append(session)
        elif session_time >= yesterday:
            groups[key_yesterday].append(session)
        elif session_time >= week_ago:
            groups[key_week].append(session)
        elif session_time >= month_ago:
            groups[key_month].append(session)
        else:
            groups[key_older].append(session)

    return {k: v for k, v in groups.items() if v}


def display_sessions_list(
    agent: BaseAgent,
    sessions: list[Session],
    show_metadata_summary: bool = True,
) -> None:
    if not sessions:
        print(i18n.t(Keys.NO_SESSIONS_PAREN))
        return

    for session in sessions:
        title = safe_display_text(agent.get_formatted_title(session))
        if show_metadata_summary:
            summary = safe_display_text(format_session_metadata_summary(agent, session))
            print(f"   • {title}")
            print(f"     {summary}")
        else:
            uri = safe_display_text(agent.get_session_uri(session))
            print(f"   • {title} {uri}")


def export_sessions_for_formats(
    agent: BaseAgent,
    sessions: list[Session],
    formats: list[str],
    output_base_dir: Path,
    *,
    output_base_dirs: dict[str, Path] | None = None,
) -> ExportRunResult:
    print(render_terminal_message(Keys.EXPORTING_AGENT, agent_name=agent.display_name))

    def _output_dir_for_format(output_format: str) -> Path:
        format_base_dir = (
            output_base_dirs.get(output_format, output_base_dir) if output_base_dirs is not None else output_base_dir
        )
        return format_base_dir / agent.name

    result = execute_exports(
        agent,
        sessions,
        formats,
        _output_dir_for_format,
        session_uris={session.id: agent.get_session_uri(session) for session in sessions},
    )
    for attempt in result.attempts:
        if attempt.output_path is not None:
            print(
                render_terminal_message(
                    Keys.EXPORT_SUCCESS_FORMAT,
                    title=attempt.session.title[:50],
                    format=attempt.output_format,
                    filename=attempt.output_path.name,
                )
            )
            continue

        error = attempt.error or RuntimeError("export failed without an error")
        diagnostic = error if isinstance(error, DiagnosticError) else wrap_runtime_fetch_error(error, agent=agent)
        print(render_diagnostic(diagnostic, t=i18n.t))

    return result


@contextmanager
def show_loading(message: str, interval_seconds: float = 0.1) -> Iterator[None]:
    """Show loading status for long-running operations."""
    safe_message = safe_display_text(message)
    if not sys.stderr.isatty():
        print(safe_message, file=sys.stderr)
        yield
        return

    stop_event = threading.Event()
    spinner_frames = "|/-\\"

    def _write_frame(frame: str) -> None:
        sys.stderr.write(f"\r{frame} {safe_message}")
        sys.stderr.flush()

    def _spin() -> None:
        idx = 0
        while not stop_event.wait(interval_seconds):
            _write_frame(spinner_frames[idx % len(spinner_frames)])
            idx += 1

    spinner_thread = threading.Thread(target=_spin, daemon=True)
    _write_frame(spinner_frames[0])
    spinner_thread.start()
    try:
        yield
    finally:
        stop_event.set()
        spinner_thread.join(timeout=max(0.3, interval_seconds * 3))
        clear_width = len(safe_message) + 4
        sys.stderr.write("\r" + (" " * clear_width) + "\r")
        sys.stderr.flush()


def is_option_specified(argv: list[str], short_option: str, long_option: str) -> bool:
    return any(arg.partition("=")[0] in (short_option, long_option) for arg in argv)


def resolve_output_base_dir(
    *,
    cli_output: str | None,
    output_specified: bool,
    export_output: str,
    output_format: str,
) -> Path:
    if output_specified and cli_output:
        return Path(cli_output)
    if output_format in {"json", "raw"} and export_output:
        return Path(export_output)
    return DEFAULT_OUTPUT_BASE_DIR


def render_query_summary(spec: QuerySpec) -> str:
    if (
        spec.project_path is None
        and spec.agent_names is None
        and spec.roles is None
        and spec.limit is None
        and spec.keyword
    ):
        return safe_display_text(spec.keyword)

    parts: list[str] = []
    if spec.project_path is not None:
        parts.append(render_terminal_message(Keys.QUERY_SUMMARY_PATH, path=spec.project_path))
    if spec.keyword:
        parts.append(render_terminal_message(Keys.QUERY_SUMMARY_KEYWORD, keyword=spec.keyword))
    if spec.agent_names:
        providers = safe_display_text(",".join(sorted(spec.agent_names)))
        parts.append(f"providers={providers}")
    if spec.roles:
        roles = safe_display_text(",".join(sorted(spec.roles)))
        parts.append(f"roles={roles}")
    if spec.limit is not None:
        parts.append(f"limit={spec.limit}")
    return "；".join(parts) if parts else i18n.t(Keys.QUERY_SUMMARY_ALL_SESSIONS)


def apply_query_filter(agent: BaseAgent, sessions: list[Session], spec: QuerySpec | None) -> list[Session]:
    if spec is None:
        return sessions
    if spec.project_path is None and spec.roles is None and spec.limit is None and spec.keyword is not None:
        if spec.agent_names is not None and agent.name not in spec.agent_names:
            return []
        return filter_sessions(agent, sessions, spec.keyword)
    return filter_sessions_by_query(agent, sessions, spec)


def collect_query_matches(
    agents: list[BaseAgent],
    *,
    days: int,
    spec: QuerySpec,
    scanner: AgentScanner | None = None,
) -> dict[str, list[Session]]:
    matches: list[SearchSessionMatch] = []
    session_scanner = scanner if scanner is not None else AgentScanner(agents)
    for agent, sessions in session_scanner.get_sessions(days, agents=agents):
        matches.extend(query_session_matches(agent, sessions, spec))

    limited_matches = limit_query_session_matches(matches, spec.limit)
    grouped: dict[str, list[Session]] = {}
    for match in limited_matches:
        grouped.setdefault(match.agent.name, []).append(match.session)
    return grouped


def collect_search_matches(
    agents: list[BaseAgent],
    *,
    days: int,
    spec: QuerySpec,
    scanner: AgentScanner | None = None,
) -> list[SearchSessionMatch]:
    matches: list[SearchSessionMatch] = []
    session_scanner = scanner if scanner is not None else AgentScanner(agents)
    for agent, sessions in session_scanner.get_sessions(days, agents=agents):
        matches.extend(search_sessions_by_query(agent, sessions, spec))
    return limit_search_matches(matches, spec.limit)


def display_search_results(matches: list[SearchSessionMatch]) -> None:
    if not matches:
        print(i18n.t(Keys.SEARCH_NO_RESULTS))
        return

    for index, match in enumerate(matches, start=1):
        title = match.agent.get_formatted_title(match.session)
        uri = match.agent.get_session_uri(match.session)
        updated = to_local_datetime(match.session.updated_at).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"\n{index}. {safe_display_text(title)}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_PROVIDER)}: {safe_display_text(match.agent.display_name)}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_UPDATED)}: {updated}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_URI)}: {safe_display_text(uri)}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_RANK)}: {match.rank:.6g}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_SNIPPET)}: {safe_display_text(match.snippet)}")


def warn_list_ignored_options(output_specified: bool, format_specified: bool) -> None:
    if format_specified:
        print(i18n.t(Keys.LIST_IGNORE_FORMAT))
    if output_specified:
        print(i18n.t(Keys.LIST_IGNORE_OUTPUT))


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
