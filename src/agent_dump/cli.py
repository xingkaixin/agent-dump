"""
Command-line interface for agent-dump
"""

import argparse
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from string import Formatter
import sys
from typing import Any

from agent_dump.__about__ import __version__
from agent_dump.cli_shared import (
    is_option_specified,
    print_diagnostic as _print_diagnostic,
    resolve_effective_formats,
    validate_formats_for_mode,
)
from agent_dump.collect import request_summary_from_llm
from agent_dump.collect_workflow import handle_collect_mode as _handle_collect_mode
from agent_dump.config import handle_config_command, load_export_config, load_shortcuts_config
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
from agent_dump.query_filter import QuerySpec, parse_query_uri
from agent_dump.scanner import AgentScanner
from agent_dump.session_workflow import handle_session_modes as _handle_session_modes
from agent_dump.uri_workflow import handle_uri_mode as _handle_uri_mode

__all__ = (
    "expand_shortcut_argv",
    "handle_collect_mode",
    "handle_reindex_mode",
    "handle_session_modes",
    "handle_stats_mode",
    "handle_uri_mode",
    "main",
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


def handle_collect_mode(args: argparse.Namespace) -> int:
    """Handle `--collect` flow."""
    return _handle_collect_mode(args, scanner_factory=AgentScanner, request_summary=request_summary_from_llm)


def handle_stats_mode(args: argparse.Namespace) -> int:
    return _handle_stats_mode(args, scanner_factory=AgentScanner)


def handle_reindex_mode(args: argparse.Namespace) -> int:
    # 延迟解析 SearchIndex，保持测试可通过 patch 源模块替换
    from agent_dump.search_index import SearchIndex

    return _handle_reindex_mode(args, scanner_factory=AgentScanner, search_index_factory=SearchIndex)


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
        scanner_factory=AgentScanner,
        request_summary=request_summary_from_llm,
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
        scanner_factory=AgentScanner,
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
    parser.add_argument("-d", "-days", type=int, default=None, dest="days", help=i18n.t(Keys.CLI_DAYS_HELP))
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
    if args.days is None:
        args.days = 7
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
