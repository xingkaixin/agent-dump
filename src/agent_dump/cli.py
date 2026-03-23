"""
Command-line interface for agent-dump
"""

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.collect import (
    CollectProgressEvent,
    build_collect_final_prompt,
    collect_entries,
    emit_collect_progress,
    plan_collect_entries,
    reduce_collect_summaries,
    request_summary_from_llm,
    resolve_collect_date_range,
    summarize_collect_entries,
    write_collect_markdown,
)
from agent_dump.config import handle_config_command, load_ai_config, load_collect_config, validate_ai_config
from agent_dump.i18n import Keys, i18n, setup_i18n
from agent_dump.message_filter import get_text_content_parts, should_filter_message_for_export
from agent_dump.query_filter import filter_sessions, parse_query
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive

# Valid URI schemes and their corresponding agent names
VALID_URI_SCHEMES = {
    "opencode": "opencode",
    "codex": "codex",
    "kimi": "kimi",
    "claude": "claudecode",  # claude:// maps to claudecode agent
    "cursor": "cursor",
}
VALID_FORMATS = {"json", "markdown", "raw", "print"}
FORMAT_ALIASES = {"md": "markdown"}


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
    if event.stage == "scan_sessions":
        return i18n.t(Keys.COLLECT_PROGRESS_SCAN_SESSIONS, current=event.current, total=event.total)
    if event.stage == "plan_chunks":
        if event.current >= event.total:
            chunk_count = event.chunk_total or 0
            return i18n.t(
                Keys.COLLECT_PROGRESS_PLAN_CHUNKS_DONE,
                current=event.current,
                total=event.total,
                chunk_count=chunk_count,
            )
        return i18n.t(Keys.COLLECT_PROGRESS_PLAN_CHUNKS, current=event.current, total=event.total)
    if event.stage == "summarize_chunks":
        return i18n.t(Keys.COLLECT_PROGRESS_SUMMARIZE_CHUNKS, current=event.current, total=event.total)
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

    def _update(event: CollectProgressEvent) -> None:
        nonlocal last_rendered
        text = _format_collect_progress(event)
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
            sys.stderr.write("\r" + (" " * (len(last_rendered) + 4)) + "\r")
            sys.stderr.write(last_rendered)
            sys.stderr.write("\n")
            sys.stderr.flush()


def parse_uri(uri: str) -> tuple[str, str] | None:
    """
    Parse an agent session URI.
    Returns (scheme, session_id) if valid, None otherwise.
    """
    pattern = r"^([a-z]+)://(.+)$"
    match = re.match(pattern, uri)
    if not match:
        return None
    scheme, session_id = match.groups()
    if scheme not in VALID_URI_SCHEMES:
        return None

    # Support Codex URI variant:
    # codex://threads/<session_id> == codex://<session_id>
    if scheme == "codex" and session_id.startswith("threads/"):
        session_id = session_id.removeprefix("threads/")
        if not session_id:
            return None

    return scheme, session_id


def find_session_by_id(scanner: AgentScanner, session_id: str) -> tuple[BaseAgent, Session] | None:
    """Find a session by ID across all available agents"""
    for agent in scanner.get_available_agents():
        # Scan all sessions (use a large days value)
        sessions = agent.get_sessions(days=3650)
        for session in sessions:
            if session.id == session_id:
                return agent, session
            if agent.name == "cursor" and session.metadata.get("request_id") == session_id:
                return agent, session
    return None


def render_session_text(uri: str, session_data: dict) -> str:
    """Render session data as formatted text"""
    lines = []
    lines.append("# Session Dump")
    lines.append("")
    lines.append(f"- URI: `{uri}`")
    lines.append("")

    messages = session_data.get("messages", [])
    msg_idx = 1

    def _append_section(display_role: str, contents: list[str]) -> None:
        nonlocal msg_idx
        if not contents:
            return
        lines.append(f"## {msg_idx}. {display_role}")
        lines.append("")
        for content in contents:
            if not content:
                continue
            lines.append(content)
            lines.append("")
        msg_idx += 1

    for msg in messages:
        role = msg.get("role", "unknown")
        role_normalized = str(role).lower()
        content_parts = get_text_content_parts(msg)

        # Skip non-conversational and injected context messages
        if role_normalized == "tool":
            continue
        if should_filter_message_for_export(msg):
            continue

        # Determine display name
        if role_normalized == "user":
            display_role = "User"
        elif role_normalized == "assistant":
            display_role = "Assistant"
        else:
            display_role = str(role).capitalize()

        nickname = str(msg.get("nickname", "")).strip()
        if nickname and role_normalized == "assistant":
            display_role = f"Assistant ({nickname})"

        if content_parts:
            _append_section(display_role, content_parts)

        if role_normalized != "assistant":
            continue

        parts = msg.get("parts", [])
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool" or part.get("tool") != "subagent":
                continue

            part_nickname = str(part.get("nickname", "")).strip()
            part_display_role = f"Assistant ({part_nickname})" if part_nickname else "Assistant"
            state = part.get("state", {})
            arguments = state.get("arguments")
            prompt = ""
            if isinstance(arguments, dict):
                prompt = str(arguments.get("message", "")).strip()
                if not prompt:
                    prompt = json.dumps(arguments, ensure_ascii=False, indent=2)
            elif isinstance(arguments, str):
                prompt = arguments.strip()

            if prompt:
                _append_section(part_display_role, [prompt])

    return "\n".join(lines)


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
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("exported JSON payload is not an object")
    payload["summary"] = summary_markdown
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    for session in sessions:
        session_time = session.created_at

        if isinstance(session_time, (int, float)):
            # Assume milliseconds if large number
            if session_time > 1e10:
                session_time = datetime.fromtimestamp(session_time / 1000)
            else:
                session_time = datetime.fromtimestamp(session_time)

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
    if save is None:
        return None

    candidate = Path(save)
    default_name = f"agent-dump-collect-{since_date.strftime('%Y%m%d')}-{until_date.strftime('%Y%m%d')}.md"

    if candidate.exists():
        return candidate / default_name if candidate.is_dir() else candidate

    if candidate.suffix.lower() == ".md":
        return candidate

    return candidate / default_name


def display_sessions_list(
    agent: BaseAgent, sessions: list[Session], page_size: int = 20, show_pagination: bool = True
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
    """Export a single session to Markdown"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{session_id}.md"
    output_path.write_text(render_session_text(uri, session_data), encoding="utf-8")
    return output_path


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
    if output_format == "json":
        return agent.export_session(session, output_dir)
    if output_format == "raw":
        return agent.export_raw_session(session, output_dir)
    if output_format == "markdown":
        effective_session_data = session_data if session_data is not None else agent.get_session_data(session)
        effective_session_uri = session_uri if session_uri is not None else agent.get_session_uri(session)
        return export_session_markdown(effective_session_uri, effective_session_data, session.id, output_dir)

    raise ValueError(f"Unsupported export format: {output_format}")


def export_sessions_for_formats(
    agent: BaseAgent,
    sessions: list[Session],
    formats: list[str],
    output_base_dir: Path,
) -> list[Path]:
    """Export multiple sessions in one or more file formats."""
    output_dir = output_base_dir / agent.name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(i18n.t(Keys.EXPORTING_AGENT, agent_name=agent.display_name))
    exported: list[Path] = []
    for session in sessions:
        session_data: dict[str, Any] | None = None
        session_uri: str | None = None
        for output_format in formats:
            try:
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
                print(
                    i18n.t(
                        Keys.EXPORT_ERROR_FORMAT,
                        title=session.title[:50],
                        format=output_format,
                        error=e,
                    )
                )

    return exported


def export_sessions_markdown(agent: BaseAgent, sessions: list[Session], output_base_dir: Path) -> list[Path]:
    """Export multiple sessions to Markdown"""
    return export_sessions_for_formats(agent, sessions, ["markdown"], output_base_dir)


def is_option_specified(argv: list[str], short_option: str, long_option: str) -> bool:
    """Check whether a CLI option is explicitly specified"""
    return any(arg in (short_option, long_option) or arg.startswith(f"{long_option}=") for arg in argv)


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
        raise ValueError("cursor-uri-format")


def warn_list_ignored_options(output_specified: bool, format_specified: bool) -> None:
    """Warn when --list mode receives options that have no effect"""
    if format_specified:
        print(i18n.t(Keys.LIST_IGNORE_FORMAT))
    if output_specified:
        print(i18n.t(Keys.LIST_IGNORE_OUTPUT))


def get_supported_agent_locations() -> list[str]:
    """Describe supported agent storage locations."""
    open_code_default = "LOCALAPPDATA/opencode/opencode.db or APPDATA/opencode/opencode.db"
    if os.name != "nt":
        open_code_default = "~/.local/share/opencode/opencode.db"

    return [
        f"  - OpenCode: XDG_DATA_HOME/opencode/opencode.db or {open_code_default}",
        "  - Codex: CODEX_HOME/sessions or ~/.codex/sessions",
        "  - Kimi: KIMI_SHARE_DIR/sessions or ~/.kimi/sessions",
        "  - Claude Code: CLAUDE_CONFIG_DIR/projects or ~/.claude/projects",
        "  - Cursor: CURSOR_DATA_PATH or ~/Library/Application Support/Cursor/User/*",
        "  - Local development fallback: data/opencode, data/codex, data/kimi, data/claudecode",
    ]


def handle_collect_mode(args: argparse.Namespace) -> int:
    """Handle `--collect` flow."""
    if args.uri or args.interactive or args.list:
        print(i18n.t(Keys.COLLECT_MODE_CONFLICT))
        return 1

    try:
        since_date, until_date = resolve_collect_date_range(args.since, args.until)
    except ValueError as e:
        if str(e) == "since_after_until":
            print(i18n.t(Keys.COLLECT_DATE_RANGE_INVALID))
        else:
            print(i18n.t(Keys.COLLECT_DATE_FORMAT_INVALID))
        return 1

    config = load_ai_config()
    valid, errors = validate_ai_config(config)
    if not valid or config is None:
        if "missing_file" in errors:
            print(i18n.t(Keys.COLLECT_CONFIG_MISSING))
        else:
            print(i18n.t(Keys.COLLECT_CONFIG_INCOMPLETE, fields=",".join(errors)))
        print(i18n.t(Keys.COLLECT_CONFIG_HINT))
        return 1
    collect_config = load_collect_config()

    scanner = AgentScanner()
    available_agents = scanner.get_available_agents()
    if not available_agents:
        print(i18n.t(Keys.NO_AGENTS_FOUND))
        return 1

    phase = "read"
    try:
        with show_collect_progress() as update_progress:
            entries, has_truncated = collect_entries(
                agents=available_agents,
                since_date=since_date,
                until_date=until_date,
                collect_config=collect_config,
                render_session_text_fn=render_session_text,
                progress_callback=update_progress,
            )
            if not entries:
                print(i18n.t(Keys.COLLECT_NO_SESSIONS, since=since_date.isoformat(), until=until_date.isoformat()))
                return 1
            planned_entries = plan_collect_entries(entries, progress_callback=update_progress)
            phase = "summarize"
            session_summaries = summarize_collect_entries(
                config=config,
                planned_entries=planned_entries,
                summary_concurrency=collect_config.summary_concurrency,
                progress_callback=update_progress,
            )
            phase = "render"
            emit_collect_progress(
                update_progress,
                stage="render_final",
                current=0,
                total=2,
                message="render final",
            )
            aggregate = reduce_collect_summaries(
                config=config,
                session_summaries=session_summaries,
                progress_callback=update_progress,
            )
            emit_collect_progress(
                update_progress,
                stage="render_final",
                current=1,
                total=2,
                message="render final",
            )
            prompt = build_collect_final_prompt(
                since_date=since_date,
                until_date=until_date,
                aggregate=aggregate,
                has_truncated=has_truncated,
            )
            markdown = request_summary_from_llm(config, prompt)
            emit_collect_progress(
                update_progress,
                stage="render_final",
                current=2,
                total=2,
                message="render final",
            )
            emit_collect_progress(
                update_progress,
                stage="write_output",
                current=0,
                total=1,
                message="write output",
            )
            phase = "write"
            output_path = write_collect_markdown(
                markdown,
                since_date=since_date,
                until_date=until_date,
                output_path=resolve_collect_save_path(args.save, since_date=since_date, until_date=until_date),
            )
            emit_collect_progress(
                update_progress,
                stage="write_output",
                current=1,
                total=1,
                message="write output",
            )
    except Exception as e:
        if phase == "read":
            print(i18n.t(Keys.COLLECT_READ_FAILED, error=e))
        else:
            print(i18n.t(Keys.COLLECT_API_FAILED, error=e))
        return 1

    print(markdown)
    print(i18n.t(Keys.COLLECT_OUTPUT_SAVED, path=str(output_path)))
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
    argv = sys.argv[1:]
    output_specified = is_option_specified(argv, "-output", "--output")
    format_specified = is_option_specified(argv, "-format", "--format")

    parser = argparse.ArgumentParser(description=i18n.t(Keys.CLI_DESC))
    parser.add_argument("uri", nargs="?", help=i18n.t(Keys.CLI_URI_HELP))
    parser.add_argument("-d", "-days", type=int, default=7, dest="days", help=i18n.t(Keys.CLI_DAYS_HELP))
    parser.add_argument(
        "-output",
        "--output",
        type=str,
        default="./sessions",
        help=i18n.t(Keys.CLI_OUTPUT_HELP),
    )
    parser.add_argument("-format", "--format", type=str, default=None, help=i18n.t(Keys.CLI_FORMAT_HELP))
    parser.add_argument("-summary", "--summary", action="store_true", help=i18n.t(Keys.CLI_SUMMARY_HELP))
    parser.add_argument("--collect", action="store_true", help=i18n.t(Keys.CLI_COLLECT_HELP))
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
    args = parser.parse_args()
    if args.summary and not args.uri:
        print(i18n.t(Keys.SUMMARY_IGNORED_NON_URI_WARNING))

    if args.config_action:
        return handle_config_command(args.config_action)
    if args.collect:
        return handle_collect_mode(args)

    is_uri_mode = bool(args.uri)
    try:
        output_formats = resolve_effective_formats(args, is_uri_mode=is_uri_mode, format_specified=format_specified)
        validate_formats_for_mode(output_formats, is_uri_mode=is_uri_mode, is_list_mode=args.list)
    except ValueError as e:
        if str(e) == "interactive-print":
            print(i18n.t(Keys.INTERACTIVE_FORMAT_INVALID))
            return 1
        parser.error(i18n.t(Keys.CLI_FORMAT_INVALID, value=args.format or ""))

    # Handle URI mode first
    if is_uri_mode:
        uri_result = parse_uri(args.uri)
        if uri_result is None:
            print(i18n.t(Keys.URI_INVALID_FORMAT, uri=args.uri))
            print(i18n.t(Keys.URI_SUPPORTED_FORMATS))
            print("  - opencode://<session_id>")
            print("  - codex://<session_id>")
            print("  - codex://threads/<session_id>")
            print("  - kimi://<session_id>")
            print("  - claude://<session_id>")
            print("  - cursor://<requestid>")
            return 1

        scheme, session_id = uri_result

        # Scan for available agents
        scanner = AgentScanner()
        available_agents = scanner.get_available_agents()

        if not available_agents:
            print(i18n.t(Keys.NO_AGENTS_FOUND))
            return 1

        # Find the session
        result = find_session_by_id(scanner, session_id)
        if result is None:
            print(i18n.t(Keys.SESSION_NOT_FOUND, uri=args.uri))
            return 1

        agent, session = result

        # Verify the URI scheme matches the agent
        expected_agent_name = VALID_URI_SCHEMES.get(scheme)
        if agent.name != expected_agent_name:
            print(i18n.t(Keys.URI_SCHEME_MISMATCH, uri=args.uri))
            print(i18n.t(Keys.URI_BELONGS_TO, agent_display_name=agent.display_name, scheme=scheme))
            return 1
        try:
            validate_uri_agent_formats(agent, output_formats)
        except ValueError as e:
            if str(e) == "cursor-uri-format":
                print("Cursor URI 模式仅支持 json 与 print 格式，不支持 raw/markdown。")
                return 1
            raise

        # Get session data and render
        try:
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

            file_formats = [fmt for fmt in output_formats if fmt != "print"]
            output_dir = Path(args.output) / agent.name
            for output_format in file_formats:
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
            return 0
        except Exception as e:
            print(i18n.t(Keys.FETCH_DATA_FAILED, error=e))
            return 1

    # If --interactive or --list not specified, but filters are, enable --list
    # If nothing specified, show help
    if not args.interactive and not args.list:
        if args.days != 7 or args.query:
            args.list = True
        else:
            parser.print_help()
            return

    print("🚀 Agent Session Exporter\n")
    print("=" * 60 + "\n")

    # Scan for available agents
    scanner = AgentScanner()
    valid_agents = {agent.name for agent in scanner.agents}
    try:
        query_spec = parse_query(args.query, valid_agents=valid_agents)
    except ValueError as e:
        print(i18n.t(Keys.QUERY_INVALID, error=e))
        return 1

    available_agents = scanner.get_available_agents()

    if not available_agents:
        print(i18n.t(Keys.NO_AGENTS_FOUND))
        print(i18n.t(Keys.SUPPORTED_AGENTS))
        for location in get_supported_agent_locations():
            print(location)
        return

    if query_spec and query_spec.agent_names:
        available_agents = [agent for agent in available_agents if agent.name in query_spec.agent_names]
        if not available_agents:
            print(i18n.t(Keys.NO_AGENTS_IN_QUERY))
            return 0 if args.list else 1

    # List mode
    if args.list:
        warn_list_ignored_options(output_specified=output_specified, format_specified=format_specified)
        if query_spec:
            print(i18n.t(Keys.LIST_HEADER_FILTERED, days=args.days, keyword=query_spec.keyword))
        else:
            print(i18n.t(Keys.LIST_HEADER, days=args.days))
        print("-" * 60)

        for agent in available_agents:
            # Get filtered sessions with days parameter
            sessions = agent.get_sessions(days=args.days)
            if query_spec:
                sessions = filter_sessions(agent, sessions, query_spec.keyword)

            print(f"\n📁 {agent.display_name} ({len(sessions)} {i18n.t(Keys.SESSION_COUNT_SUFFIX)})")

            if sessions:
                should_quit = display_sessions_list(
                    agent,
                    sessions,
                    page_size=max(len(sessions), 1),
                    show_pagination=False,
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
    matched_sessions_by_agent: dict[str, list[Session]] = {}
    session_counts: dict[str, int] | None = None

    if query_spec:
        session_counts = {}
        for agent in available_agents:
            sessions = agent.get_sessions(days=args.days)
            matched_sessions = filter_sessions(agent, sessions, query_spec.keyword)
            if matched_sessions:
                matched_sessions_by_agent[agent.name] = matched_sessions
                session_counts[agent.name] = len(matched_sessions)

        interactive_agents = [agent for agent in available_agents if agent.name in matched_sessions_by_agent]
        if not interactive_agents:
            print(i18n.t(Keys.NO_SESSIONS_MATCHING_KEYWORD, days=args.days, keyword=query_spec.keyword))
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
            print(i18n.t(Keys.NO_SESSIONS_MATCHING_KEYWORD, days=args.days, keyword=query_spec.keyword))
        else:
            print(i18n.t(Keys.NO_SESSIONS_FOUND, days=args.days))
        return 1

    if query_spec:
        print(i18n.t(Keys.SESSIONS_FOUND_FILTERED, count=len(sessions), days=args.days, keyword=query_spec.keyword))
    else:
        print(i18n.t(Keys.SESSIONS_FOUND, count=len(sessions), days=args.days))

    # Show warning if too many sessions
    if len(sessions) > 100:
        print(i18n.t(Keys.MANY_SESSIONS_WARNING, count=len(sessions)))
        print(i18n.t(Keys.MANY_SESSIONS_EXAMPLE))

    # Select sessions
    selected_sessions = select_sessions_interactive(sessions, selected_agent)
    if not selected_sessions:
        print("\n" + i18n.t(Keys.NO_SESSION_SELECTED))
        return 1

    print(i18n.t(Keys.SESSIONS_SELECTED_COUNT, count=len(selected_sessions)))

    # Export
    output_base_dir = Path(args.output)
    exported = export_sessions_for_formats(selected_agent, selected_sessions, output_formats, output_base_dir)

    print(i18n.t(Keys.EXPORT_SUMMARY, count=len(exported), path=f"{output_base_dir}/{selected_agent.name}"))
    return 0


if __name__ == "__main__":
    main()
