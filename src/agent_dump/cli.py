"""
Command-line interface for agent-dump
"""

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from string import Formatter
import sys
import threading
from typing import Any

from agent_dump.__about__ import __version__
from agent_dump.agent_registry import get_supported_uri_examples
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import (
    DEFAULT_OUTPUT_BASE_DIR,
    VALID_URI_SCHEMES,
    apply_query_filter,
    apply_summary_to_json_export,
    build_no_agents_found_diagnostic as _build_no_agents_found_diagnostic,
    collect_query_matches,
    collect_search_matches,
    display_search_results,
    display_sessions_list,
    export_session_in_format,
    export_sessions_for_formats,
    find_session_by_id,
    format_session_metadata_summary,
    get_supported_agent_locations,
    group_sessions_by_time,
    is_option_specified,
    parse_format_spec,
    parse_uri,
    print_diagnostic as _print_diagnostic,
    render_agent_search_roots as _render_agent_search_roots,
    render_query_summary,
    render_session_head,
    render_session_text,
    resolve_effective_formats,
    resolve_output_base_dir,
    validate_formats_for_mode,
    validate_uri_agent_formats,
    warn_list_ignored_options,
    wrap_runtime_fetch_error as _wrap_runtime_fetch_error,
)
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
from agent_dump.collect_models import collect_fields_for
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
    ParsedUri,
    invalid_query_or_uri,
    unsupported_capability,
)
from agent_dump.i18n import Keys, i18n, setup_i18n
from agent_dump.maintenance_workflow import (
    handle_reindex_mode as _handle_reindex_mode,
    handle_stats_mode as _handle_stats_mode,
)
from agent_dump.query_filter import QuerySpec, parse_query, parse_query_uri
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive
from agent_dump.session_workflow import SessionModeDeps, handle_session_modes as _handle_session_modes
from agent_dump.uri_workflow import UriModeDeps, handle_uri_mode as _handle_uri_mode

__all__ = (
    "DEFAULT_OUTPUT_BASE_DIR",
    "VALID_URI_SCHEMES",
    "apply_query_filter",
    "apply_summary_to_json_export",
    "collect_query_matches",
    "collect_search_matches",
    "display_search_results",
    "display_sessions_list",
    "expand_shortcut_argv",
    "export_session_in_format",
    "export_sessions_for_formats",
    "find_session_by_id",
    "format_session_metadata_summary",
    "get_supported_agent_locations",
    "group_sessions_by_time",
    "handle_collect_mode",
    "handle_reindex_mode",
    "handle_stats_mode",
    "is_option_specified",
    "main",
    "parse_format_spec",
    "parse_uri",
    "render_query_summary",
    "render_session_head",
    "render_session_text",
    "resolve_collect_save_path",
    "resolve_effective_formats",
    "resolve_output_base_dir",
    "show_collect_progress",
    "show_loading",
    "validate_formats_for_mode",
    "validate_uri_agent_formats",
    "warn_list_ignored_options",
)


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


def resolve_collect_save_path(save: str | None, *, since_date: date, until_date: date) -> Path | None:
    """Resolve collect output path from an optional save spec."""
    return _resolve_collect_save_path(save, since_date=since_date, until_date=until_date)


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
            collect_fields_for=collect_fields_for,
            i18n_t=i18n.t,
            keys=Keys,
        ),
    )


def handle_stats_mode(args: argparse.Namespace) -> int:
    return _handle_stats_mode(args, scanner_factory=AgentScanner)


def handle_reindex_mode(args: argparse.Namespace) -> int:
    # 延迟解析 SearchIndex，保持测试可通过 patch 源模块替换
    from agent_dump.search_index import SearchIndex

    return _handle_reindex_mode(args, scanner_factory=AgentScanner, search_index_factory=SearchIndex)


def _build_uri_deps() -> UriModeDeps:
    return UriModeDeps(
        scanner_factory=AgentScanner,
        parse_uri=parse_uri,
        find_session_by_id=find_session_by_id,
        render_session_head=render_session_head,
        maybe_generate_uri_summary=maybe_generate_uri_summary,
        render_session_text=render_session_text,
        export_session_in_format=export_session_in_format,
        apply_summary_to_json_export=apply_summary_to_json_export,
        resolve_output_base_dir=resolve_output_base_dir,
        validate_uri_agent_formats=validate_uri_agent_formats,
        print_diagnostic=_print_diagnostic,
        build_no_agents_found_diagnostic=_build_no_agents_found_diagnostic,
        wrap_runtime_fetch_error=_wrap_runtime_fetch_error,
        render_agent_search_roots=_render_agent_search_roots,
        get_supported_uri_examples=get_supported_uri_examples,
    )


def _build_session_deps() -> SessionModeDeps:
    return SessionModeDeps(
        scanner_factory=AgentScanner,
        parse_query=parse_query,
        collect_query_matches=collect_query_matches,
        collect_search_matches=collect_search_matches,
        display_search_results=display_search_results,
        display_sessions_list=display_sessions_list,
        select_agent_interactive=select_agent_interactive,
        select_sessions_interactive=select_sessions_interactive,
        export_sessions_for_formats=export_sessions_for_formats,
        resolve_output_base_dir=resolve_output_base_dir,
        render_query_summary=render_query_summary,
        warn_list_ignored_options=warn_list_ignored_options,
        print_diagnostic=_print_diagnostic,
        build_no_agents_found_diagnostic=_build_no_agents_found_diagnostic,
        render_agent_search_roots=_render_agent_search_roots,
    )


def handle_uri_mode(
    args: argparse.Namespace,
    *,
    output_formats: list[str],
    output_specified: bool,
    export_config: Any,
) -> int:
    return _handle_uri_mode(
        args,
        output_formats=output_formats,
        output_specified=output_specified,
        export_config=export_config,
        deps=_build_uri_deps(),
    )


def handle_session_modes(
    args: argparse.Namespace,
    *,
    query_uri_spec: QuerySpec | None,
    output_specified: bool,
    format_specified: bool,
    output_formats: list[str],
    export_config: Any,
    print_help: Callable[[], None],
) -> int | None:
    return _handle_session_modes(
        args,
        query_uri_spec=query_uri_spec,
        output_specified=output_specified,
        format_specified=format_specified,
        output_formats=output_formats,
        export_config=export_config,
        print_help=print_help,
        deps=_build_session_deps(),
    )


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
    parser.add_argument(
        "--collect-mode",
        type=str,
        choices=["pm", "insight"],
        default="pm",
        dest="collect_mode",
        help=i18n.t(Keys.CLI_COLLECT_MODE_HELP),
    )
    parser.add_argument("--dry-run", action="store_true", help=i18n.t(Keys.CLI_DRY_RUN_HELP))
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
        "--search",
        type=str,
        default=None,
        help=i18n.t(Keys.CLI_SEARCH_HELP),
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help=i18n.t(Keys.CLI_REINDEX_HELP),
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
    if args.head and not is_uri_mode:
        print(i18n.t(Keys.HEAD_IGNORED_NON_URI_WARNING))

    if args.config_action:
        return handle_config_command(args.config_action)
    if args.collect:
        return handle_collect_mode(args)
    if args.stats:
        return handle_stats_mode(args)
    if args.reindex:
        return handle_reindex_mode(args)

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

    if is_uri_mode:
        return handle_uri_mode(
            args,
            output_formats=output_formats,
            output_specified=output_specified,
            export_config=export_config,
        )

    return handle_session_modes(
        args,
        query_uri_spec=query_uri_spec,
        output_specified=output_specified,
        format_specified=format_specified,
        output_formats=output_formats,
        export_config=export_config,
        print_help=parser.print_help,
    )


if __name__ == "__main__":
    main()
