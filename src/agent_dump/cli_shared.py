import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import sys
import threading
from typing import Any, cast

from agent_dump.agent_registry import (
    get_supported_agent_locations as _get_supported_agent_locations,
    get_uri_scheme_map,
)
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import (
    DiagnosticError,
    invalid_query_or_uri,
    render_diagnostic,
    root_not_found,
    unsupported_capability,
)
from agent_dump.exporting import ExportRunResult, execute_exports
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot
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
from agent_dump.rendering import (
    apply_summary_to_json_export as _apply_summary_to_json_export,
    export_session_in_format as _export_session_in_format,
    format_session_metadata_summary as _format_session_metadata_summary,
    render_session_head as _render_session_head,
    render_session_text as _render_session_text,
)
from agent_dump.scanner import AgentScanner, sessions_per_agent
from agent_dump.text_safety import safe_display_text
from agent_dump.time_utils import get_local_timezone, to_local_datetime
from agent_dump.uri_support import find_session_by_id as _find_session_by_id, parse_uri as _parse_uri

VALID_URI_SCHEMES = get_uri_scheme_map()
VALID_FORMATS = {"json", "markdown", "raw", "print"}
FORMAT_ALIASES = {"md": "markdown"}
DEFAULT_OUTPUT_BASE_DIR = Path("./sessions")


def parse_uri(uri: str) -> tuple[str, str] | None:
    return _parse_uri(uri)


def find_session_by_id(
    scanner: AgentScanner,
    session_id: str,
    *,
    agent_name: str | None = None,
) -> tuple[BaseAgent, Session] | None:
    return _find_session_by_id(scanner, session_id, agent_name=agent_name)


def render_session_text(uri: str, session_data: dict[str, Any]) -> str:
    return _render_session_text(uri, session_data)


def format_session_metadata_summary(agent: BaseAgent, session: Session) -> str:
    return _format_session_metadata_summary(agent, session)


def render_session_head(uri: str, session_head: dict[str, Any]) -> str:
    return _render_session_head(uri, session_head)


def apply_summary_to_json_export(output_path: Path, summary_markdown: str) -> None:
    _apply_summary_to_json_export(output_path, summary_markdown)


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
    page_size: int = 20,
    show_pagination: bool = True,
    show_metadata_summary: bool = True,
) -> bool:
    total = len(sessions)

    if total == 0:
        print(i18n.t(Keys.NO_SESSIONS_PAREN))
        return False

    current_page = 0
    total_pages = (total + page_size - 1) // page_size

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total)

        for i in range(start_idx, end_idx):
            session = sessions[i]
            title = safe_display_text(agent.get_formatted_title(session))
            if show_metadata_summary:
                summary = safe_display_text(format_session_metadata_summary(agent, session))
                print(f"   • {title}")
                print(f"     {summary}")
            else:
                uri = safe_display_text(agent.get_session_uri(session))
                print(f"   • {title} {uri}")

        if show_pagination and total_pages > 1:
            print(
                "\n   "
                + i18n.t(Keys.PAGINATION_INFO, current=current_page + 1, total=total_pages, total_sessions=total)
            )

            if current_page < total_pages - 1:
                print("   " + i18n.t(Keys.PAGINATION_PROMPT))
                try:
                    user_input = input("> ").strip().lower()
                    if user_input == "q":
                        return True
                    current_page += 1
                    print()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return True
            else:
                print("   " + i18n.t(Keys.PAGINATION_DONE))
                break
        else:
            if total > page_size:
                print("\n   " + i18n.t(Keys.PAGINATION_REMAINING, count=total - page_size))
            break

    return False


def export_session_in_format(
    agent: BaseAgent,
    session: Session,
    output_dir: Path,
    output_format: str,
    *,
    session_data: dict[str, Any] | None = None,
    session_uri: str | None = None,
) -> Path:
    return _export_session_in_format(
        agent,
        session,
        output_dir,
        output_format,
        session_data=session_data,
        session_uri=session_uri,
    )


def export_sessions_for_formats(
    agent: BaseAgent,
    sessions: list[Session],
    formats: list[str],
    output_base_dir: Path,
    *,
    output_base_dirs: dict[str, Path] | None = None,
) -> ExportRunResult:
    print(i18n.t(Keys.EXPORTING_AGENT, agent_name=agent.display_name))

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
                i18n.t(
                    Keys.EXPORT_SUCCESS_FORMAT,
                    title=attempt.session.title[:50],
                    format=attempt.output_format,
                    filename=attempt.output_path.name,
                )
            )
            continue

        error = attempt.error or RuntimeError("export failed without an error")
        print(
            i18n.t(
                Keys.EXPORT_ERROR_FORMAT,
                title=attempt.session.title[:50],
                format=attempt.output_format,
                error=str(error),
            )
        )
        diagnostic = error if isinstance(error, DiagnosticError) else wrap_runtime_fetch_error(error, agent=agent)
        print(render_diagnostic(diagnostic, t=i18n.t))

    return result


@contextmanager
def show_loading(message: str, interval_seconds: float = 0.1) -> Iterator[None]:
    """Show loading status for long-running operations."""
    if not sys.stderr.isatty():
        print(message, file=sys.stderr)
        yield
        return

    stop_event = threading.Event()
    spinner_frames = "|/-\\"

    def _write_frame(frame: str) -> None:
        sys.stderr.write(f"\r{frame} {message}")
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
        clear_width = len(message) + 4
        sys.stderr.write("\r" + (" " * clear_width) + "\r")
        sys.stderr.flush()


def is_option_specified(argv: list[str], short_option: str, long_option: str) -> bool:
    return any(arg in (short_option, long_option) or arg.startswith(f"{long_option}=") for arg in argv)


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


def parse_format_spec(raw: str) -> list[str]:
    formats: list[str] = []
    seen: set[str] = set()

    for part in raw.split(","):
        normalized = FORMAT_ALIASES.get(part.strip().lower(), part.strip().lower())
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


def resolve_effective_formats(args: argparse.Namespace, is_uri_mode: bool, format_specified: bool) -> list[str]:
    if format_specified and args.format:
        return parse_format_spec(args.format)
    return ["print"] if is_uri_mode else ["json"]


def render_query_summary(spec: QuerySpec) -> str:
    if (
        spec.project_path is None
        and spec.agent_names is None
        and spec.roles is None
        and spec.limit is None
        and spec.keyword
    ):
        return spec.keyword

    parts: list[str] = []
    if spec.project_path is not None:
        parts.append(i18n.t(Keys.QUERY_SUMMARY_PATH, path=spec.project_path))
    if spec.keyword:
        parts.append(i18n.t(Keys.QUERY_SUMMARY_KEYWORD, keyword=spec.keyword))
    if spec.agent_names:
        providers = ",".join(sorted(spec.agent_names))
        parts.append(f"providers={providers}")
    if spec.roles:
        roles = ",".join(sorted(spec.roles))
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
) -> dict[str, list[Session]]:
    matches: list[SearchSessionMatch] = []
    for agent, sessions in sessions_per_agent(agents, days):
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
) -> list[SearchSessionMatch]:
    matches: list[SearchSessionMatch] = []
    for agent, sessions in sessions_per_agent(agents, days):
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
        print(f"   {i18n.t(Keys.SEARCH_RESULT_PROVIDER)}: {match.agent.display_name}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_UPDATED)}: {updated}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_URI)}: {safe_display_text(uri)}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_RANK)}: {match.rank:.6g}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_SNIPPET)}: {safe_display_text(match.snippet)}")


def validate_formats_for_mode(formats: list[str], is_uri_mode: bool, is_list_mode: bool) -> None:
    if is_list_mode or is_uri_mode:
        return
    if "print" in formats:
        raise ValueError("interactive-print")


def validate_uri_agent_formats(agent: BaseAgent, formats: list[str]) -> None:
    unsupported = [fmt for fmt in formats if fmt in agent.unsupported_uri_formats]
    if unsupported:
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
                i18n.t(Keys.DIAG_STEP_DROP_FORMATS, formats=", ".join(f"`{fmt}`" for fmt in unsupported)),
                i18n.t(Keys.DIAG_STEP_EXPORT_JSON_FIRST),
            ),
        )


def warn_list_ignored_options(output_specified: bool, format_specified: bool) -> None:
    if format_specified:
        print(i18n.t(Keys.LIST_IGNORE_FORMAT))
    if output_specified:
        print(i18n.t(Keys.LIST_IGNORE_OUTPUT))


def get_supported_agent_locations() -> list[str]:
    return _get_supported_agent_locations()


def render_agent_search_roots(agents: list[BaseAgent] | list[Any]) -> tuple[str, ...]:
    roots: list[str] = []
    for agent in agents:
        get_search_roots = getattr(agent, "get_search_roots", None)
        display_name = getattr(agent, "display_name", getattr(agent, "name", "agent"))
        if not callable(get_search_roots):
            continue
        provider_roots = [root.render() for root in cast(tuple[SearchRoot, ...], get_search_roots())]
        if not provider_roots:
            continue
        roots.extend(f"{display_name}: {entry}" for entry in provider_roots)
    return tuple(roots)


def print_diagnostic(error: DiagnosticError) -> None:
    print(render_diagnostic(error, t=i18n.t))


def build_no_agents_found_diagnostic(scanner: AgentScanner) -> DiagnosticError:
    agents = getattr(scanner, "agents", [])
    searched_roots = render_agent_search_roots(agents)
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
