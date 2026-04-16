"""
Command-line interface for agent-dump
"""

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from string import Formatter
import sys
import threading
from typing import Any, cast

from agent_dump.__about__ import __version__
from agent_dump.agent_registry import (
    get_supported_agent_locations as _get_supported_agent_locations,
    get_supported_uri_examples,
    get_uri_scheme_map,
)
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.collect import (
    CollectProgressEvent,
    build_collect_final_prompt,
    build_collect_run_stats,
    collect_entries,
    create_collect_logger,
    emit_collect_progress,
    plan_collect_entries,
    reduce_collect_summaries,
    request_summary_from_llm,
    resolve_collect_date_range,
    summarize_collect_entries,
    write_collect_markdown,
)
from agent_dump.collect_workflow import (
    CollectWorkflowDeps,
    handle_collect_mode as _handle_collect_mode,
    resolve_collect_save_path as _resolve_collect_save_path,
)
from agent_dump.config import (
    handle_config_command,
    load_ai_config,
    load_collect_config,
    load_export_config,
    load_logging_config,
    load_shortcuts_config,
    validate_ai_config,
)
from agent_dump.diagnostics import (
    DiagnosticError,
    ParsedUri,
    invalid_query_or_uri,
    render_diagnostic,
    root_not_found,
    session_not_found,
    unsupported_capability,
)
from agent_dump.i18n import Keys, i18n, setup_i18n
from agent_dump.paths import SearchRoot
from agent_dump.query_filter import (
    QuerySpec,
    filter_sessions,
    filter_sessions_by_query,
    limit_query_matches,
    parse_query,
    parse_query_uri,
)
from agent_dump.rendering import (
    apply_summary_to_json_export as _apply_summary_to_json_export,
    export_session_in_format as _export_session_in_format,
    export_session_markdown as _export_session_markdown,
    format_session_metadata_summary as _format_session_metadata_summary,
    render_session_head as _render_session_head,
    render_session_text as _render_session_text,
)
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive
from agent_dump.time_utils import get_local_timezone, to_local_datetime
from agent_dump.uri_support import find_session_by_id as _find_session_by_id, parse_uri as _parse_uri

VALID_URI_SCHEMES = get_uri_scheme_map()
VALID_FORMATS = {"json", "markdown", "raw", "print"}
FORMAT_ALIASES = {"md": "markdown"}
DEFAULT_OUTPUT_BASE_DIR = Path("./sessions")


def _parse_shortcut_date(value: str) -> date:
    normalized = value.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    raise ValueError("invalid_date")


def _build_shortcut_variables(params: tuple[str, ...], values: tuple[str, ...]) -> dict[str, str]:
    variables = dict(zip(params, values, strict=True))
    raw_date = variables.get("date")
    if raw_date is None:
        return variables

    parsed_date = _parse_shortcut_date(raw_date)
    variables["date"] = parsed_date.strftime("%Y%m%d")
    variables["year"] = parsed_date.strftime("%Y")
    variables["month"] = parsed_date.strftime("%m")
    variables["year_month"] = parsed_date.strftime("%Y-%m")
    return variables


def _render_shortcut_arg(template: str, variables: dict[str, str]) -> str:
    formatter = Formatter()
    rendered: list[str] = []
    for literal_text, field_name, format_spec, conversion in formatter.parse(template):
        rendered.append(literal_text)
        if field_name is None:
            continue
        if format_spec or conversion:
            raise ValueError("invalid_template")
        if field_name not in variables:
            raise ValueError(f"unknown_variable:{field_name}")
        rendered.append(variables[field_name])

    result = "".join(rendered)
    if result.startswith("~"):
        return str(Path(result).expanduser())
    return result


def expand_shortcut_argv(argv: list[str]) -> list[str]:
    """Expand configured shortcut preset into regular CLI argv."""
    if "--shortcut" not in argv:
        return argv

    shortcut_index = argv.index("--shortcut")
    prefix = argv[:shortcut_index]
    suffix = argv[shortcut_index + 1 :]
    if not suffix:
        raise ValueError("shortcut_missing_name")

    shortcut_name = suffix[0].strip()
    if not shortcut_name:
        raise ValueError("shortcut_missing_name")

    value_tokens: list[str] = []
    remainder_index = len(suffix)
    for index, token in enumerate(suffix[1:], start=1):
        if token.startswith("-"):
            remainder_index = index
            break
        value_tokens.append(token)

    remainder = suffix[remainder_index:]
    shortcuts = load_shortcuts_config()
    shortcut = shortcuts.get(shortcut_name)
    if shortcut is None:
        raise ValueError(f"shortcut_not_found:{shortcut_name}")

    expected = len(shortcut.params)
    actual = len(value_tokens)
    if actual != expected:
        raise ValueError(f"shortcut_args_mismatch:{shortcut_name}:{expected}:{actual}")

    variables = _build_shortcut_variables(shortcut.params, tuple(value_tokens))
    expanded_args = [_render_shortcut_arg(arg, variables) for arg in shortcut.args]
    return prefix + expanded_args + remainder


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


def _format_collect_progress(event: CollectProgressEvent) -> str:
    """Format one collect progress event for stderr."""
    if event.stage == "collect_start":
        return i18n.t(Keys.COLLECT_PROGRESS_START, since=event.since, until=event.until)
    if event.stage == "collect_overview":
        breakdown = ", ".join(
            f"{agent_name} {count}" for agent_name, count in (event.agent_session_counts or {}).items()
        )
        overview = i18n.t(
            Keys.COLLECT_PROGRESS_OVERVIEW,
            session_count=event.session_count or event.current,
            chunk_count=event.chunk_count or 0,
            concurrency=event.concurrency or 1,
        )
        if not breakdown:
            return overview
        return "\n".join([overview, i18n.t(Keys.COLLECT_PROGRESS_AGENT_BREAKDOWN, breakdown=breakdown)])
    if event.stage == "scan_sessions":
        return i18n.t(Keys.COLLECT_PROGRESS_SCAN_SESSIONS, current=event.current, total=event.total)
    if event.stage == "plan_chunks":
        if event.current >= event.total:
            return i18n.t(
                Keys.COLLECT_PROGRESS_PLAN_CHUNKS_DONE,
                session_count=event.current,
                chunk_count=event.chunk_total or 0,
            )
        return i18n.t(Keys.COLLECT_PROGRESS_PLAN_CHUNKS, current=event.current, total=event.total)
    if event.stage == "summarize_chunks":
        return i18n.t(
            Keys.COLLECT_PROGRESS_SUMMARIZE_CHUNKS,
            current=event.current,
            total=event.total,
            concurrency=event.concurrency or 1,
        )
    if event.stage == "merge_sessions":
        return i18n.t(Keys.COLLECT_PROGRESS_MERGE_SESSIONS, current=event.current, total=event.total)
    if event.stage == "tree_reduction":
        level = event.level or 1
        return i18n.t(Keys.COLLECT_PROGRESS_TREE_REDUCTION, level=level, current=event.current, total=event.total)
    if event.stage == "render_final":
        return i18n.t(Keys.COLLECT_PROGRESS_RENDER_FINAL, current=event.current, total=event.total)
    if event.stage == "write_output":
        return i18n.t(Keys.COLLECT_PROGRESS_WRITE_OUTPUT, current=event.current, total=event.total)
    return event.message


@contextmanager
def show_collect_progress() -> Iterator[Callable[[CollectProgressEvent], None]]:
    """Show collect multi-stage progress on stderr."""
    is_tty = sys.stderr.isatty()
    stop_event = threading.Event()
    progress_lock = threading.Lock()
    spinner_frames = "|/-\\"
    spinner_thread: threading.Thread | None = None
    last_rendered = ""

    def _clear_tty_line(text: str) -> None:
        width = len(text) + 4
        sys.stderr.write("\r" + (" " * width) + "\r")

    def _update(event: CollectProgressEvent) -> None:
        nonlocal last_rendered
        text = _format_collect_progress(event)
        if event.stage in {"collect_start", "collect_overview"}:
            if is_tty:
                with progress_lock:
                    if last_rendered:
                        _clear_tty_line(last_rendered)
                    print(text, file=sys.stderr)
            else:
                print(text, file=sys.stderr)
            return
        with progress_lock:
            last_rendered = text
        if is_tty:
            return
        print(text, file=sys.stderr)

    if is_tty:

        def _spin() -> None:
            idx = 0
            while not stop_event.wait(0.1):
                with progress_lock:
                    text = last_rendered
                    if not text:
                        continue
                    sys.stderr.write(f"\r{spinner_frames[idx % len(spinner_frames)]} {text}")
                    sys.stderr.flush()
                idx += 1

        spinner_thread = threading.Thread(target=_spin, daemon=True)
        spinner_thread.start()

    try:
        yield _update
    finally:
        if is_tty:
            stop_event.set()
            if spinner_thread is not None:
                spinner_thread.join(timeout=0.3)
        if last_rendered and is_tty:
            with progress_lock:
                _clear_tty_line(last_rendered)
                sys.stderr.write(last_rendered)
                sys.stderr.write("\n")
                sys.stderr.flush()


def parse_uri(uri: str) -> tuple[str, str] | None:
    """Parse an agent session URI."""
    return _parse_uri(uri)


def find_session_by_id(scanner: AgentScanner, session_id: str) -> tuple[BaseAgent, Session] | None:
    """Find a session by ID across all available agents."""
    return _find_session_by_id(scanner, session_id)


def render_session_text(uri: str, session_data: dict[str, Any]) -> str:
    """Render session data as formatted text."""
    return _render_session_text(uri, session_data)


def format_session_metadata_summary(agent: BaseAgent, session: Session) -> str:
    """Render a unified reduced metadata summary for one session."""
    return _format_session_metadata_summary(agent, session)


def render_session_head(uri: str, session_head: dict[str, Any]) -> str:
    """Render lightweight session metadata as formatted text."""
    return _render_session_head(uri, session_head)


def build_uri_summary_prompt(uri: str, rendered_session_text: str) -> str:
    """Build a single-session summary prompt for URI mode."""
    return "\n".join(
        [
            "你是一个严谨的会话总结助手。",
            "请基于下面的单个会话内容输出 Markdown 总结。",
            "要求：",
            "1. 只基于给定内容，不要编造。",
            "2. 总结关键目标、主要改动、风险/异常、结果。",
            "3. 若信息不足，明确指出。",
            "",
            f"会话 URI: {uri}",
            "",
            "会话内容：",
            rendered_session_text,
        ]
    )


def apply_summary_to_json_export(output_path: Path, summary_markdown: str) -> None:
    """Inject summary markdown into exported JSON as top-level `summary`."""
    _apply_summary_to_json_export(output_path, summary_markdown)


def maybe_generate_uri_summary(
    *,
    enabled: bool,
    output_formats: list[str],
    uri: str,
    agent: BaseAgent,
    session: Session,
    session_data: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Best-effort URI summary generation. Returns possibly-loaded session_data and summary."""
    if not enabled:
        return session_data, None

    if "json" not in output_formats:
        print(i18n.t(Keys.URI_SUMMARY_NO_JSON_WARNING))
        return session_data, None

    config = load_ai_config()
    valid, errors = validate_ai_config(config)
    if not valid or config is None:
        if "missing_file" in errors:
            print(i18n.t(Keys.URI_SUMMARY_CONFIG_MISSING_WARNING))
        else:
            print(i18n.t(Keys.URI_SUMMARY_CONFIG_INCOMPLETE_WARNING, fields=",".join(errors)))
        return session_data, None

    effective_session_data = session_data if session_data is not None else agent.get_session_data(session)
    rendered = render_session_text(uri, effective_session_data)
    prompt = build_uri_summary_prompt(uri, rendered)

    try:
        with show_loading(i18n.t(Keys.URI_SUMMARY_LOADING)):
            summary_markdown = request_summary_from_llm(config, prompt)
    except Exception as e:
        print(i18n.t(Keys.URI_SUMMARY_API_FAILED_WARNING, error=e))
        return effective_session_data, None

    return effective_session_data, summary_markdown


def format_relative_time(time_value: datetime | float) -> str:
    """Format time as relative description"""
    if isinstance(time_value, (int, float)):
        time_value = datetime.fromtimestamp(time_value)

    now = datetime.now()
    delta = now - time_value

    if delta.days == 0:
        if delta.seconds < 3600:
            minutes = delta.seconds // 60
            return i18n.t(Keys.TIME_MINUTES_AGO, minutes=minutes) if minutes > 0 else i18n.t(Keys.TIME_JUST_NOW)
        hours = delta.seconds // 3600
        return i18n.t(Keys.TIME_HOURS_AGO, hours=hours)
    elif delta.days == 1:
        return i18n.t(Keys.TIME_YESTERDAY)
    elif delta.days < 7:
        return i18n.t(Keys.TIME_DAYS_AGO, days=delta.days)
    elif delta.days < 30:
        weeks = delta.days // 7
        return i18n.t(Keys.TIME_WEEKS_AGO, weeks=weeks)
    else:
        return time_value.strftime("%Y-%m-%d")


def group_sessions_by_time(sessions: list[Session]) -> dict[str, list[Session]]:
    """Group sessions by relative time periods"""
    groups: dict[str, list[Session]] = {
        i18n.t(Keys.TIME_TODAY): [],
        i18n.t(Keys.TIME_YESTERDAY): [],
        i18n.t(Keys.TIME_THIS_WEEK): [],
        i18n.t(Keys.TIME_THIS_MONTH): [],
        i18n.t(Keys.TIME_OLDER): [],
    }

    # Map keys for lookup
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

    # Remove empty groups
    return {k: v for k, v in groups.items() if v}


def resolve_collect_save_path(save: str | None, *, since_date: date, until_date: date) -> Path | None:
    """Resolve collect output path from an optional save spec."""
    return _resolve_collect_save_path(save, since_date=since_date, until_date=until_date)


def display_sessions_list(
    agent: BaseAgent,
    sessions: list[Session],
    page_size: int = 20,
    show_pagination: bool = True,
    show_metadata_summary: bool = True,
) -> bool:
    """Display sessions with pagination support.

    Returns:
        True if user chose to quit, False otherwise.
    """
    total = len(sessions)

    if total == 0:
        print(i18n.t(Keys.NO_SESSIONS_PAREN))
        return False

    # Show all sessions with pagination
    current_page = 0
    total_pages = (total + page_size - 1) // page_size

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total)

        # Display current page
        for i in range(start_idx, end_idx):
            session = sessions[i]
            title = agent.get_formatted_title(session)
            if show_metadata_summary:
                summary = format_session_metadata_summary(agent, session)
                print(f"   • {title}")
                print(f"     {summary}")
            else:
                uri = agent.get_session_uri(session)
                print(f"   • {title} {uri}")

        # Show pagination info
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
                        return True  # User wants to quit entirely
                    current_page += 1
                    print()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return True  # User interrupted, quit entirely
            else:
                print("   " + i18n.t(Keys.PAGINATION_DONE))
                break
        else:
            if total > page_size:
                print("\n   " + i18n.t(Keys.PAGINATION_REMAINING, count=total - page_size))
            break

    return False


def export_sessions(agent: BaseAgent, sessions: list[Session], output_base_dir: Path) -> list[Path]:
    """Export multiple sessions"""
    return export_sessions_for_formats(agent, sessions, ["json"], output_base_dir)


def export_session_markdown(uri: str, session_data: dict, session_id: str, output_dir: Path) -> Path:
    """Export a single session to Markdown."""
    return _export_session_markdown(uri, session_data, session_id, output_dir)


def export_session_in_format(
    agent: BaseAgent,
    session: Session,
    output_dir: Path,
    output_format: str,
    *,
    session_data: dict[str, Any] | None = None,
    session_uri: str | None = None,
) -> Path:
    """Export one session in the requested file format."""
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
) -> list[Path]:
    """Export multiple sessions in one or more file formats."""
    print(i18n.t(Keys.EXPORTING_AGENT, agent_name=agent.display_name))
    exported: list[Path] = []
    for session in sessions:
        session_data: dict[str, Any] | None = None
        session_uri: str | None = None
        for output_format in formats:
            try:
                format_base_dir = (
                    output_base_dirs.get(output_format, output_base_dir)
                    if output_base_dirs is not None
                    else output_base_dir
                )
                output_dir = format_base_dir / agent.name
                output_dir.mkdir(parents=True, exist_ok=True)
                if output_format == "markdown":
                    session_data = session_data if session_data is not None else agent.get_session_data(session)
                    session_uri = session_uri if session_uri is not None else agent.get_session_uri(session)

                output_path = export_session_in_format(
                    agent,
                    session,
                    output_dir,
                    output_format,
                    session_data=session_data,
                    session_uri=session_uri,
                )
                exported.append(output_path)
                print(
                    i18n.t(
                        Keys.EXPORT_SUCCESS_FORMAT,
                        title=session.title[:50],
                        format=output_format,
                        filename=output_path.name,
                    )
                )
            except Exception as e:
                print(i18n.t(Keys.EXPORT_ERROR_FORMAT, title=session.title[:50], format=output_format, error=str(e)))
                diagnostic = e if isinstance(e, DiagnosticError) else _wrap_runtime_fetch_error(e, agent=agent)
                print(render_diagnostic(diagnostic, t=i18n.t))

    return exported


def export_sessions_markdown(agent: BaseAgent, sessions: list[Session], output_base_dir: Path) -> list[Path]:
    """Export multiple sessions to Markdown"""
    return export_sessions_for_formats(agent, sessions, ["markdown"], output_base_dir)


def is_option_specified(argv: list[str], short_option: str, long_option: str) -> bool:
    """Check whether a CLI option is explicitly specified"""
    return any(arg in (short_option, long_option) or arg.startswith(f"{long_option}=") for arg in argv)


def resolve_output_base_dir(
    *,
    cli_output: str | None,
    output_specified: bool,
    export_output: str,
    output_format: str,
) -> Path:
    """Resolve effective output base directory for one file format."""
    if output_specified and cli_output:
        return Path(cli_output)
    if output_format in {"json", "raw"} and export_output:
        return Path(export_output)
    return DEFAULT_OUTPUT_BASE_DIR


def parse_format_spec(raw: str) -> list[str]:
    """Parse a comma-separated format specification."""
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
    """Resolve effective output formats by mode and explicit user input."""
    if format_specified and args.format:
        return parse_format_spec(args.format)
    return ["print"] if is_uri_mode else ["json"]


def render_query_summary(spec: QuerySpec) -> str:
    """Render one compact query description for user-facing messages."""
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
        parts.append(f"路径={spec.project_path}")
    if spec.keyword:
        parts.append(f"关键词={spec.keyword}")
    if spec.agent_names:
        providers = ",".join(sorted(spec.agent_names))
        parts.append(f"providers={providers}")
    if spec.roles:
        roles = ",".join(sorted(spec.roles))
        parts.append(f"roles={roles}")
    if spec.limit is not None:
        parts.append(f"limit={spec.limit}")
    return "；".join(parts) if parts else "全部会话"


def apply_query_filter(agent: BaseAgent, sessions: list[Session], spec: QuerySpec | None) -> list[Session]:
    """Apply query filters while preserving legacy keyword-only behavior."""
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
    """Collect matched sessions for all agents and apply one global query limit."""
    matched_pairs: list[tuple[BaseAgent, Session]] = []
    for agent in agents:
        sessions = agent.get_sessions(days=days)
        matched_sessions = apply_query_filter(agent, sessions, spec)
        matched_pairs.extend((agent, session) for session in matched_sessions)

    limited_pairs = limit_query_matches(matched_pairs, spec.limit)
    grouped: dict[str, list[Session]] = {}
    for agent, session in limited_pairs:
        grouped.setdefault(agent.name, []).append(session)
    return grouped


def validate_formats_for_mode(formats: list[str], is_uri_mode: bool, is_list_mode: bool) -> None:
    """Validate format combinations for the current mode."""
    if is_list_mode or is_uri_mode:
        return
    if "print" in formats:
        raise ValueError("interactive-print")


def validate_uri_agent_formats(agent: BaseAgent, formats: list[str]) -> None:
    """Validate URI format restrictions for special agents."""
    if agent.name != "cursor":
        return
    unsupported = [fmt for fmt in formats if fmt in {"raw", "markdown"}]
    if unsupported:
        requested = ",".join(unsupported)
        raise unsupported_capability(
            "当前 URI 请求了 Cursor 不支持的导出能力。",
            capability_gap=f"Cursor URI 仅支持 json 与 print；当前请求了 {requested}",
            next_steps=(
                "移除 `raw` 或 `markdown`，改用 `json` 或 `print`。",
                "若需要进一步处理，先导出 JSON 再做转换。",
            ),
        )


def warn_list_ignored_options(output_specified: bool, format_specified: bool) -> None:
    """Warn when --list mode receives options that have no effect"""
    if format_specified:
        print(i18n.t(Keys.LIST_IGNORE_FORMAT))
    if output_specified:
        print(i18n.t(Keys.LIST_IGNORE_OUTPUT))


def get_supported_agent_locations() -> list[str]:
    """Describe supported agent storage locations."""
    return _get_supported_agent_locations()


def _render_agent_search_roots(agents: list[BaseAgent] | list[Any]) -> tuple[str, ...]:
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


def _print_diagnostic(error: DiagnosticError) -> None:
    print(render_diagnostic(error, t=i18n.t))


def _build_no_agents_found_diagnostic(scanner: AgentScanner) -> DiagnosticError:
    agents = getattr(scanner, "agents", [])
    searched_roots = _render_agent_search_roots(agents)
    if not searched_roots:
        searched_roots = tuple(location.strip() for location in get_supported_agent_locations())
    return root_not_found(
        "未找到任何可用的本地会话数据。",
        searched_roots=searched_roots,
        next_steps=(
            "确认对应 agent 已在本机生成过会话数据。",
            "若使用自定义目录，检查相关环境变量是否指向正确位置。",
            "若在开发环境，检查 `data/<agent>` 回退目录是否存在。",
        ),
    )


def _wrap_runtime_fetch_error(exc: Exception, *, agent: BaseAgent | None = None) -> DiagnosticError:
    searched_roots = _render_agent_search_roots([agent]) if agent is not None else ()
    return (
        invalid_query_or_uri(
            "读取会话数据失败。",
            details=(str(exc),),
            next_steps=(
                "检查本地会话源文件或数据库是否仍存在。",
                "若问题持续，先用 `agent-dump --list` 缩小范围再重试。",
            ),
        )
        if not searched_roots
        else root_not_found(
            "读取会话数据失败。",
            details=(str(exc),),
            searched_roots=searched_roots,
            next_steps=(
                "检查本地会话源文件或数据库是否仍存在。",
                "若问题持续，先用 `agent-dump --list` 缩小范围再重试。",
            ),
        )
    )


def handle_collect_mode(args: argparse.Namespace) -> int:
    """Handle `--collect` flow."""
    return _handle_collect_mode(
        args,
        CollectWorkflowDeps(
            resolve_collect_date_range=resolve_collect_date_range,
            load_ai_config=load_ai_config,
            validate_ai_config=validate_ai_config,
            load_collect_config=load_collect_config,
            load_logging_config=load_logging_config,
            create_collect_logger=create_collect_logger,
            scanner_factory=AgentScanner,
            show_collect_progress=show_collect_progress,
            collect_entries=collect_entries,
            plan_collect_entries=plan_collect_entries,
            build_collect_run_stats=build_collect_run_stats,
            summarize_collect_entries=summarize_collect_entries,
            emit_collect_progress=emit_collect_progress,
            reduce_collect_summaries=reduce_collect_summaries,
            build_collect_final_prompt=build_collect_final_prompt,
            request_summary_from_llm=request_summary_from_llm,
            write_collect_markdown=write_collect_markdown,
            resolve_collect_save_path=resolve_collect_save_path,
            render_session_text=render_session_text,
            parse_query_uri=parse_query_uri,
            i18n_t=i18n.t,
            keys=Keys,
        ),
    )


def handle_stats_mode(args: argparse.Namespace) -> int:
    """Handle `--stats` flow."""
    scanner = AgentScanner()
    available_agents = scanner.get_available_agents()

    if not available_agents:
        _print_diagnostic(_build_no_agents_found_diagnostic(scanner))
        return 1

    query_spec: QuerySpec | None = None
    if args.query:
        valid_agents = {agent.name for agent in scanner.agents}
        try:
            query_spec = parse_query(args.query, valid_agents=valid_agents)
        except ValueError as e:
            _print_diagnostic(
                invalid_query_or_uri(
                    "查询条件无效。",
                    details=(str(e),),
                    next_steps=(
                        "使用 `关键词` 或 `agent1,agent2:关键词` 格式。",
                        "如需路径作用域查询，改用 `agents://<path>?q=<keyword>&providers=<names>`。",
                    ),
                )
            )
            return 1

    if query_spec and query_spec.agent_names:
        available_agents = [agent for agent in available_agents if agent.name in query_spec.agent_names]
        if not available_agents:
            _print_diagnostic(
                root_not_found(
                    "查询范围内没有可用 provider。",
                    searched_roots=_render_agent_search_roots(scanner.agents),
                    details=(f"query providers: {','.join(sorted(query_spec.agent_names))}",),
                    next_steps=(
                        "确认这些 provider 在本机上确实存在会话数据。",
                        "放宽 providers 范围，或先不加 provider 过滤执行 `--list`。",
                    ),
                )
            )
            return 0

    all_sessions: list[tuple[BaseAgent, Session]] = []
    for agent in available_agents:
        sessions = agent.get_sessions(days=args.days)
        if query_spec is not None:
            sessions = apply_query_filter(agent, sessions, query_spec)
        for session in sessions:
            all_sessions.append((agent, session))

    if not all_sessions:
        print(i18n.t(Keys.STATS_NO_SESSIONS, days=args.days))
        return 0

    total_sessions = len(all_sessions)
    total_messages = 0
    agent_stats: dict[str, dict[str, int]] = {}

    for agent, session in all_sessions:
        agent_name = agent.display_name
        if agent_name not in agent_stats:
            agent_stats[agent_name] = {"sessions": 0, "messages": 0}
        agent_stats[agent_name]["sessions"] += 1

        message_count = session.metadata.get("message_count")
        if isinstance(message_count, int):
            agent_stats[agent_name]["messages"] += message_count
            total_messages += message_count

    print(i18n.t(Keys.STATS_HEADER, days=args.days))
    print()
    print(i18n.t(Keys.STATS_TOTAL_SESSIONS, count=total_sessions))
    if total_messages > 0:
        print(i18n.t(Keys.STATS_TOTAL_MESSAGES, count=total_messages))
    print()

    print(i18n.t(Keys.STATS_BY_AGENT))
    for name in sorted(agent_stats):
        stats = agent_stats[name]
        if total_messages > 0:
            print(i18n.t(Keys.STATS_AGENT_ROW, name=name, sessions=stats["sessions"], messages=stats["messages"]))
        else:
            print(f"  {name}: {stats['sessions']} {i18n.t(Keys.SESSION_COUNT_SUFFIX)}")
    print()

    # Group all sessions by time regardless of agent
    grouped = group_sessions_by_time([session for _, session in all_sessions])
    if grouped:
        print(i18n.t(Keys.STATS_BY_TIME))
        for label, sessions in grouped.items():
            print(i18n.t(Keys.STATS_TIME_ROW, label=label, count=len(sessions)))

    return 0


def main():
    """Main entry point"""

    # Pre-parse language argument
    lang_arg = None
    for i, arg in enumerate(sys.argv):
        if arg == "--lang":
            if i + 1 < len(sys.argv):
                lang_arg = sys.argv[i + 1]
                break
        elif arg.startswith("--lang="):
            lang_arg = arg.split("=", 1)[1]
            break

    setup_i18n(lang_arg)
    try:
        argv = expand_shortcut_argv(sys.argv[1:])
    except ValueError as exc:
        message = str(exc)
        if message == "shortcut_missing_name":
            print(i18n.t(Keys.SHORTCUT_MISSING_NAME))
            return 1
        if message == "invalid_date":
            print(i18n.t(Keys.SHORTCUT_DATE_INVALID))
            return 1
        if message == "invalid_template":
            print(i18n.t(Keys.SHORTCUT_TEMPLATE_INVALID))
            return 1
        if message.startswith("shortcut_not_found:"):
            _, shortcut_name = message.split(":", 1)
            print(i18n.t(Keys.SHORTCUT_NOT_FOUND, name=shortcut_name))
            return 1
        if message.startswith("shortcut_args_mismatch:"):
            _, shortcut_name, expected, actual = message.split(":", 3)
            print(i18n.t(Keys.SHORTCUT_ARGS_MISMATCH, name=shortcut_name, expected=expected, actual=actual))
            return 1
        if message.startswith("unknown_variable:"):
            _, variable_name = message.split(":", 1)
            print(i18n.t(Keys.SHORTCUT_UNKNOWN_VARIABLE, name=variable_name))
            return 1
        raise

    output_specified = is_option_specified(argv, "-output", "--output")
    format_specified = is_option_specified(argv, "-format", "--format")

    parser = argparse.ArgumentParser(description=i18n.t(Keys.CLI_DESC))
    parser.add_argument("uri", nargs="?", help=i18n.t(Keys.CLI_URI_HELP))
    parser.add_argument("-d", "-days", type=int, default=7, dest="days", help=i18n.t(Keys.CLI_DAYS_HELP))
    parser.add_argument(
        "-output",
        "--output",
        type=str,
        default=None,
        help=i18n.t(Keys.CLI_OUTPUT_HELP),
    )
    parser.add_argument("-format", "--format", type=str, default=None, help=i18n.t(Keys.CLI_FORMAT_HELP))
    parser.add_argument("--head", action="store_true", help=i18n.t(Keys.CLI_HEAD_HELP))
    parser.add_argument("-summary", "--summary", action="store_true", help=i18n.t(Keys.CLI_SUMMARY_HELP))
    parser.add_argument("--collect", action="store_true", help=i18n.t(Keys.CLI_COLLECT_HELP))
    parser.add_argument("--stats", action="store_true", help=i18n.t(Keys.CLI_STATS_HELP))
    parser.add_argument("--shortcut", type=str, default=None, help=i18n.t(Keys.CLI_SHORTCUT_HELP))
    parser.add_argument("-since", "--since", type=str, default=None, help=i18n.t(Keys.CLI_SINCE_HELP))
    parser.add_argument("-until", "--until", type=str, default=None, help=i18n.t(Keys.CLI_UNTIL_HELP))
    parser.add_argument("--save", type=str, default=None, help=i18n.t(Keys.CLI_SAVE_HELP))
    parser.add_argument(
        "-config",
        "--config",
        type=str,
        choices=["view", "edit"],
        default=None,
        dest="config_action",
        help=i18n.t(Keys.CLI_CONFIG_HELP),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help=i18n.t(Keys.CLI_LIST_HELP),
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help=i18n.t(Keys.CLI_INTERACTIVE_HELP),
    )
    parser.add_argument(
        "--no-metadata-summary",
        action="store_true",
        help=i18n.t(Keys.CLI_NO_METADATA_SUMMARY_HELP),
    )
    parser.add_argument(
        "-p",
        "-page-size",
        type=int,
        default=20,
        dest="page_size",
        help=i18n.t(Keys.CLI_PAGE_SIZE_HELP),
    )
    parser.add_argument(
        "-q",
        "-query",
        type=str,
        default=None,
        dest="query",
        help=i18n.t(Keys.CLI_QUERY_HELP),
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        choices=["en", "zh"],
        help=i18n.t(Keys.CLI_LANG_HELP),
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"agent-dump {__version__}",
        help=i18n.t(Keys.CLI_VERSION_HELP),
    )
    args = parser.parse_args(argv)
    query_uri_spec: QuerySpec | None = None
    if args.uri and args.uri.startswith("agents://"):
        valid_agents = {agent.name for agent in AgentScanner().agents}
        try:
            query_uri_spec = parse_query_uri(args.uri, valid_agents=valid_agents, cwd=Path.cwd())
        except ValueError as e:
            _print_diagnostic(
                invalid_query_or_uri(
                    "agents:// 查询无效。",
                    details=(str(e),),
                    parsed_uri=ParsedUri(raw=args.uri),
                    next_steps=(
                        "检查 `agents://<path>?q=<keyword>&providers=<names>` 结构是否完整。",
                        "不要把 `agents://...` 与 `-q/--query` 同时使用。",
                    ),
                )
            )
            return 1

    is_query_uri_mode = query_uri_spec is not None
    is_uri_mode = bool(args.uri) and not is_query_uri_mode

    if args.query and is_query_uri_mode:
        _print_diagnostic(
            invalid_query_or_uri(
                "查询参数组合无效。",
                details=("agents:// 查询不能与 -q/--query 同时使用",),
                parsed_uri=ParsedUri(raw=args.uri),
                next_steps=("删除 `-q/--query`，或改用普通列表/交互模式。",),
            )
        )
        return 1

    if args.summary and not is_uri_mode:
        print(i18n.t(Keys.SUMMARY_IGNORED_NON_URI_WARNING))
    show_metadata_summary = not args.no_metadata_summary
    if args.head and not is_uri_mode:
        print(i18n.t(Keys.HEAD_IGNORED_NON_URI_WARNING))

    if args.config_action:
        return handle_config_command(args.config_action)
    if args.collect:
        return handle_collect_mode(args)
    if args.stats:
        return handle_stats_mode(args)

    export_config = load_export_config()

    if is_uri_mode and args.head:
        if format_specified:
            print(i18n.t(Keys.URI_HEAD_WITH_FORMAT_ERROR))
            return 1
        if args.summary:
            print(i18n.t(Keys.URI_HEAD_WITH_SUMMARY_ERROR))
            return 1
        output_formats: list[str] = []
    else:
        try:
            output_formats = resolve_effective_formats(args, is_uri_mode=is_uri_mode, format_specified=format_specified)
            validate_formats_for_mode(output_formats, is_uri_mode=is_uri_mode, is_list_mode=args.list)
        except ValueError as e:
            if str(e) == "interactive-print":
                _print_diagnostic(
                    unsupported_capability(
                        "当前模式不支持 print 导出。",
                        capability_gap="--interactive 模式不支持 print；仅支持 json、markdown、raw",
                        next_steps=("移除 `print`，改用 `json`、`markdown` 或 `raw`。",),
                    )
                )
                return 1
            parser.error(i18n.t(Keys.CLI_FORMAT_INVALID, value=args.format or ""))

    # Handle URI mode first
    if is_uri_mode:
        uri_result = parse_uri(args.uri)
        if uri_result is None:
            _print_diagnostic(
                invalid_query_or_uri(
                    "URI 格式无效。",
                    details=("无法解析为受支持的 `<scheme>://<session_id>` 形式。",),
                    parsed_uri=ParsedUri(raw=args.uri),
                    next_steps=(
                        "改用受支持的 URI scheme。",
                        *[example.strip() for example in get_supported_uri_examples()],
                    ),
                )
            )
            return 1

        scheme, session_id = uri_result

        # Scan for available agents
        scanner = AgentScanner()
        available_agents = scanner.get_available_agents()

        if not available_agents:
            _print_diagnostic(_build_no_agents_found_diagnostic(scanner))
            return 1

        # Find the session
        result = find_session_by_id(scanner, session_id)
        if result is None:
            _print_diagnostic(
                session_not_found(
                    raw_uri=args.uri,
                    scheme=scheme,
                    session_id=session_id,
                    searched_roots=_render_agent_search_roots(scanner.agents),
                    details=("已扫描当前可用 provider，但未匹配到该 session id。",),
                    next_steps=(
                        "先运行 `agent-dump --list` 确认该会话是否仍存在。",
                        "检查 URI 中的 session id 是否完整且对应正确 provider。",
                    ),
                )
            )
            return 1

        agent, session = result

        # Verify the URI scheme matches the agent
        expected_agent_name = VALID_URI_SCHEMES.get(scheme)
        if agent.name != expected_agent_name:
            _print_diagnostic(
                invalid_query_or_uri(
                    "URI scheme 与实际会话来源不匹配。",
                    details=(f"该会话实际属于 {agent.display_name}。",),
                    parsed_uri=ParsedUri(raw=args.uri, scheme=scheme, session_id=session_id),
                    next_steps=(f"改用 `{agent.get_session_uri(session)}` 重新执行。",),
                )
            )
            return 1
        try:
            validate_uri_agent_formats(agent, output_formats)
        except DiagnosticError as e:
            _print_diagnostic(e)
            return 1

        # Get session data and render
        try:
            had_success = False
            if args.head:
                print(render_session_head(args.uri, agent.get_session_head(session)))
                return 0

            session_data: dict[str, Any] | None = None
            session_data, summary_markdown = maybe_generate_uri_summary(
                enabled=args.summary,
                output_formats=output_formats,
                uri=args.uri,
                agent=agent,
                session=session,
                session_data=session_data,
            )
            if "print" in output_formats:
                session_data = session_data if session_data is not None else agent.get_session_data(session)
                output = render_session_text(args.uri, session_data)
                print(output)
                had_success = True

            file_formats = [fmt for fmt in output_formats if fmt != "print"]
            for output_format in file_formats:
                try:
                    output_dir = (
                        resolve_output_base_dir(
                            cli_output=args.output,
                            output_specified=output_specified,
                            export_output=export_config.output,
                            output_format=output_format,
                        )
                        / agent.name
                    )
                    output_path = export_session_in_format(
                        agent,
                        session,
                        output_dir,
                        output_format,
                        session_data=session_data,
                        session_uri=args.uri,
                    )
                    if output_format == "json" and summary_markdown is not None:
                        try:
                            apply_summary_to_json_export(output_path, summary_markdown)
                            print(i18n.t(Keys.URI_SUMMARY_APPLIED, path=str(output_path)))
                        except Exception as e:
                            print(i18n.t(Keys.URI_SUMMARY_API_FAILED_WARNING, error=e))
                    print(i18n.t(Keys.URI_EXPORT_SAVED, path=str(output_path), format=output_format))
                    had_success = True
                except Exception as e:
                    diagnostic = e if isinstance(e, DiagnosticError) else _wrap_runtime_fetch_error(e, agent=agent)
                    _print_diagnostic(diagnostic)
            return 0 if had_success else 1
        except Exception as e:
            diagnostic = e if isinstance(e, DiagnosticError) else _wrap_runtime_fetch_error(e, agent=agent)
            _print_diagnostic(diagnostic)
            return 1

    # If --interactive or --list not specified, but filters are, enable --list
    # If nothing specified, show help
    if not args.interactive and not args.list:
        if args.days != 7 or args.query or is_query_uri_mode:
            args.list = True
        else:
            parser.print_help()
            return

    print("🚀 Agent Session Exporter\n")
    print("=" * 60 + "\n")

    # Scan for available agents
    scanner = AgentScanner()
    valid_agents = {agent.name for agent in scanner.agents}
    if is_query_uri_mode:
        query_spec = query_uri_spec
    else:
        try:
            query_spec = parse_query(args.query, valid_agents=valid_agents)
        except ValueError as e:
            _print_diagnostic(
                invalid_query_or_uri(
                    "查询条件无效。",
                    details=(str(e),),
                    next_steps=(
                        "使用 `关键词` 或 `agent1,agent2:关键词` 格式。",
                        "如需路径作用域查询，改用 `agents://<path>?q=<keyword>&providers=<names>`。",
                    ),
                )
            )
            return 1

    available_agents = scanner.get_available_agents()

    if not available_agents:
        _print_diagnostic(_build_no_agents_found_diagnostic(scanner))
        return

    if query_spec and query_spec.agent_names:
        available_agents = [agent for agent in available_agents if agent.name in query_spec.agent_names]
        if not available_agents:
            _print_diagnostic(
                root_not_found(
                    "查询范围内没有可用 provider。",
                    searched_roots=_render_agent_search_roots(scanner.agents),
                    details=(f"query providers: {','.join(sorted(query_spec.agent_names))}",),
                    next_steps=(
                        "确认这些 provider 在本机上确实存在会话数据。",
                        "放宽 providers 范围，或先不加 provider 过滤执行 `--list`。",
                    ),
                )
            )
            return 0 if args.list else 1

    matched_sessions_by_agent: dict[str, list[Session]] = {}
    if query_spec:
        matched_sessions_by_agent = collect_query_matches(available_agents, days=args.days, spec=query_spec)

    # List mode
    if args.list:
        warn_list_ignored_options(output_specified=output_specified, format_specified=format_specified)
        if query_spec:
            print(i18n.t(Keys.LIST_HEADER_FILTERED, days=args.days, query=render_query_summary(query_spec)))
        else:
            print(i18n.t(Keys.LIST_HEADER, days=args.days))
        print("-" * 60)

        for agent in available_agents:
            sessions = (
                matched_sessions_by_agent.get(agent.name, []) if query_spec else agent.get_sessions(days=args.days)
            )

            print(f"\n📁 {agent.display_name} ({len(sessions)} {i18n.t(Keys.SESSION_COUNT_SUFFIX)})")

            if sessions:
                should_quit = display_sessions_list(
                    agent,
                    sessions,
                    page_size=max(len(sessions), 1),
                    show_pagination=False,
                    show_metadata_summary=show_metadata_summary,
                )
                if should_quit:
                    print("\n" + "=" * 60)
                    return 0
            else:
                print(i18n.t(Keys.NO_SESSIONS_IN_DAYS, days=args.days))

        print("\n" + "=" * 60)
        print(i18n.t(Keys.HINT_INTERACTIVE))
        print()
        return 0

    # Interactive mode
    interactive_agents = available_agents
    session_counts: dict[str, int] | None = None

    if query_spec:
        session_counts = {
            agent.name: len(matched_sessions_by_agent[agent.name])
            for agent in available_agents
            if agent.name in matched_sessions_by_agent
        }
        interactive_agents = [agent for agent in available_agents if agent.name in matched_sessions_by_agent]
        if not interactive_agents:
            print(i18n.t(Keys.NO_SESSIONS_MATCHING_KEYWORD, days=args.days, query=render_query_summary(query_spec)))
            return 1

    # Select agent
    if len(interactive_agents) == 1:
        selected_agent = interactive_agents[0]
        print(i18n.t(Keys.AUTO_SELECT_AGENT, agent_name=selected_agent.display_name))
    else:
        selected_agent = select_agent_interactive(
            interactive_agents,
            days=args.days,
            session_counts=session_counts,
        )
        if not selected_agent:
            print("\n" + i18n.t(Keys.NO_AGENT_SELECTED))
            return 1
        print(i18n.t(Keys.AGENT_SELECTED, agent_name=selected_agent.display_name))

    # Get sessions for the selected agent
    if query_spec:
        sessions = matched_sessions_by_agent.get(selected_agent.name, [])
    else:
        sessions = selected_agent.get_sessions(days=args.days)

    if not sessions:
        if query_spec:
            print(i18n.t(Keys.NO_SESSIONS_MATCHING_KEYWORD, days=args.days, query=render_query_summary(query_spec)))
        else:
            print(i18n.t(Keys.NO_SESSIONS_FOUND, days=args.days))
        return 1

    if query_spec:
        print(
            i18n.t(
                Keys.SESSIONS_FOUND_FILTERED,
                count=len(sessions),
                days=args.days,
                query=render_query_summary(query_spec),
            )
        )
    else:
        print(i18n.t(Keys.SESSIONS_FOUND, count=len(sessions), days=args.days))

    # Show warning if too many sessions
    if len(sessions) > 100:
        print(i18n.t(Keys.MANY_SESSIONS_WARNING, count=len(sessions)))
        print(i18n.t(Keys.MANY_SESSIONS_EXAMPLE))

    # Select sessions
    selected_sessions = select_sessions_interactive(
        sessions,
        selected_agent,
        show_metadata_summary=show_metadata_summary,
    )
    if not selected_sessions:
        print("\n" + i18n.t(Keys.NO_SESSION_SELECTED))
        return 1

    print(i18n.t(Keys.SESSIONS_SELECTED_COUNT, count=len(selected_sessions)))

    # Export
    output_base_dirs = {
        output_format: resolve_output_base_dir(
            cli_output=args.output,
            output_specified=output_specified,
            export_output=export_config.output,
            output_format=output_format,
        )
        for output_format in output_formats
    }
    primary_output_format = output_formats[0] if output_formats else "json"
    output_base_dir = output_base_dirs.get(
        primary_output_format,
        resolve_output_base_dir(
            cli_output=args.output,
            output_specified=output_specified,
            export_output=export_config.output,
            output_format=primary_output_format,
        ),
    )
    exported = export_sessions_for_formats(
        selected_agent,
        selected_sessions,
        output_formats,
        output_base_dir,
        output_base_dirs=output_base_dirs,
    )

    summary_paths = sorted({str(path.parent) for path in exported})
    summary_path = ", ".join(summary_paths) if summary_paths else f"{output_base_dir}/{selected_agent.name}"
    print(i18n.t(Keys.EXPORT_SUMMARY, count=len(exported), path=summary_path))
    return 0


if __name__ == "__main__":
    main()
