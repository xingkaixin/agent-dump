"""
Command-line interface for agent-dump
"""

import argparse
from datetime import date, datetime
from pathlib import Path
from string import Formatter
import sys

from agent_dump.__about__ import __version__
from agent_dump.agent_registry import get_supported_uri_examples
from agent_dump.cli_shared import (
    is_option_specified,
    print_diagnostic as _print_diagnostic,
)
from agent_dump.collect import request_summary_from_llm
from agent_dump.collect_workflow import handle_collect_mode as _handle_collect_mode
from agent_dump.command_plan import (
    CollectOperation,
    CommandMode,
    CommandPlanError,
    CommandPlanErrorCode,
    CommandPlanWarning,
    CommandRequest,
    ConfigOperation,
    ReindexOperation,
    SessionOperation,
    StatsOperation,
    UriOperation,
    build_command_plan,
)
from agent_dump.config import ExportConfig, handle_config_command, load_export_config, load_shortcuts_config
from agent_dump.diagnostics import (
    DiagnosticError,
    ParsedUri,
    invalid_query_or_uri,
    unexpected_failure,
    unsupported_capability,
)
from agent_dump.i18n import Keys, i18n, setup_i18n
from agent_dump.maintenance_workflow import (
    handle_providers_mode as _handle_providers_mode,
    handle_reindex_mode as _handle_reindex_mode,
    handle_stats_mode as _handle_stats_mode,
)
from agent_dump.scanner import AgentScanner
from agent_dump.session_workflow import handle_session_modes as _handle_session_modes
from agent_dump.terminal_output import render_terminal_message
from agent_dump.uri_workflow import handle_uri_mode as _handle_uri_mode

__all__ = (
    "expand_shortcut_argv",
    "handle_collect_mode",
    "handle_providers_mode",
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


def handle_collect_mode(operation: CollectOperation) -> int:
    """Handle `--collect` flow."""
    return _handle_collect_mode(operation, scanner_factory=AgentScanner, request_summary=request_summary_from_llm)


def handle_stats_mode(operation: StatsOperation) -> int:
    return _handle_stats_mode(operation, scanner_factory=AgentScanner)


def handle_providers_mode() -> int:
    return _handle_providers_mode()


def handle_reindex_mode(operation: ReindexOperation) -> int:
    # 延迟解析 SearchIndex，保持测试可通过 patch 源模块替换
    from agent_dump.search_index import SearchIndex

    return _handle_reindex_mode(operation, scanner_factory=AgentScanner, search_index_factory=SearchIndex)


def handle_uri_mode(
    operation: UriOperation,
    *,
    export_config: ExportConfig,
) -> int:
    return _handle_uri_mode(
        operation,
        export_config=export_config,
        scanner_factory=AgentScanner,
        request_summary=request_summary_from_llm,
    )


def handle_session_modes(
    operation: SessionOperation,
    *,
    export_config: ExportConfig,
) -> int | None:
    return _handle_session_modes(
        operation,
        export_config=export_config,
        scanner_factory=AgentScanner,
    )


def _build_command_request(
    args: argparse.Namespace,
    *,
    output_specified: bool,
    format_specified: bool,
) -> CommandRequest:
    return CommandRequest(
        uri=args.uri,
        days=args.days,
        output=args.output,
        raw_format=args.format,
        output_specified=output_specified,
        format_specified=format_specified,
        head=args.head,
        summary=args.summary,
        collect=args.collect,
        collect_mode=args.collect_mode,
        dry_run=args.dry_run,
        stats=args.stats,
        providers=args.providers,
        reindex=args.reindex,
        config_action=args.config_action,
        list_requested=args.list,
        interactive=args.interactive,
        no_metadata_summary=args.no_metadata_summary,
        query=args.query,
        search=args.search,
        since=args.since,
        until=args.until,
        save=args.save,
    )


def main() -> int | None:
    """Main entry point.

    只在这里做顶层兜底：任何漏到最外层的异常都渲染成诊断块，而不是给用户一段
    traceback。SystemExit 必须原样放行，argparse 的 --help / -v / usage error
    依赖它。
    """
    try:
        return _run()
    except DiagnosticError as exc:
        _print_diagnostic(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - 顶层兜底，转成诊断后以退出码 1 结束
        _print_diagnostic(unexpected_failure(exc))
        return 1


def _run() -> int | None:
    """Parse arguments and dispatch to the selected mode."""

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
            print(render_terminal_message(Keys.SHORTCUT_NOT_FOUND, name=shortcut_name))
            return 1
        if message.startswith("shortcut_args_mismatch:"):
            _, shortcut_name, expected, actual = message.split(":", 3)
            print(
                render_terminal_message(
                    Keys.SHORTCUT_ARGS_MISMATCH,
                    name=shortcut_name,
                    expected=expected,
                    actual=actual,
                )
            )
            return 1
        if message.startswith("unknown_variable:"):
            _, variable_name = message.split(":", 1)
            print(render_terminal_message(Keys.SHORTCUT_UNKNOWN_VARIABLE, name=variable_name))
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
    parser.add_argument(
        "--providers",
        "--capabilities",
        action="store_true",
        help=i18n.t(Keys.CLI_PROVIDERS_HELP),
    )
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
    request = _build_command_request(
        args,
        output_specified=output_specified,
        format_specified=format_specified,
    )

    try:
        plan = build_command_plan(request, cwd=Path.cwd())
    except CommandPlanError as exc:
        if exc.code is CommandPlanErrorCode.QUERY_URI_INVALID:
            _print_diagnostic(
                invalid_query_or_uri(
                    i18n.t(Keys.DIAG_QUERY_URI_INVALID),
                    details=(exc.detail or exc.code.value,),
                    parsed_uri=ParsedUri(raw=request.uri or ""),
                    next_steps=(
                        i18n.t(Keys.DIAG_STEP_CHECK_QUERY_URI_SHAPE),
                        i18n.t(Keys.DIAG_STEP_NO_QUERY_URI_WITH_Q),
                    ),
                )
            )
            return 1
        if exc.code is CommandPlanErrorCode.QUERY_SPEC_INVALID:
            _print_diagnostic(
                invalid_query_or_uri(
                    i18n.t(Keys.DIAG_QUERY_SPEC_INVALID),
                    details=(exc.detail or exc.code.value,),
                    next_steps=(
                        i18n.t(Keys.DIAG_STEP_QUERY_FORMAT),
                        i18n.t(Keys.DIAG_STEP_QUERY_URI_FOR_PATH),
                    ),
                )
            )
            return 1
        if exc.code is CommandPlanErrorCode.QUERY_COMBINATION_INVALID:
            _print_diagnostic(
                invalid_query_or_uri(
                    i18n.t(Keys.DIAG_QUERY_COMBINATION_INVALID),
                    details=(i18n.t(Keys.DIAG_QUERY_URI_WITH_Q_DETAIL),),
                    parsed_uri=ParsedUri(raw=request.uri or ""),
                    next_steps=(i18n.t(Keys.DIAG_STEP_DROP_Q),),
                )
            )
            return 1
        if exc.code is CommandPlanErrorCode.COLLECT_MODE_CONFLICT:
            print(i18n.t(Keys.COLLECT_MODE_CONFLICT))
            return 1
        if exc.code is CommandPlanErrorCode.URI_INVALID:
            _print_diagnostic(
                invalid_query_or_uri(
                    i18n.t(Keys.DIAG_URI_INVALID),
                    details=(i18n.t(Keys.DIAG_URI_UNPARSEABLE),),
                    parsed_uri=ParsedUri(raw=request.uri or ""),
                    next_steps=(
                        i18n.t(Keys.DIAG_STEP_USE_SUPPORTED_SCHEME),
                        *[example.strip() for example in get_supported_uri_examples()],
                    ),
                )
            )
            return 1
        if exc.code is CommandPlanErrorCode.URI_HEAD_WITH_FORMAT:
            print(i18n.t(Keys.URI_HEAD_WITH_FORMAT_ERROR))
            return 1
        if exc.code is CommandPlanErrorCode.URI_HEAD_WITH_SUMMARY:
            print(i18n.t(Keys.URI_HEAD_WITH_SUMMARY_ERROR))
            return 1
        if exc.code is CommandPlanErrorCode.FORMAT_INVALID:
            parser.error(i18n.t(Keys.CLI_FORMAT_INVALID, value=request.raw_format or ""))
        _print_diagnostic(
            unsupported_capability(
                i18n.t(Keys.DIAG_PRINT_UNSUPPORTED_MODE),
                capability_gap=i18n.t(Keys.DIAG_PRINT_UNSUPPORTED_DETAIL),
                next_steps=(i18n.t(Keys.DIAG_STEP_DROP_PRINT),),
            )
        )
        return 1

    for warning in plan.warnings:
        if warning is CommandPlanWarning.SUMMARY_IGNORED_NON_URI:
            print(i18n.t(Keys.SUMMARY_IGNORED_NON_URI_WARNING))
        elif warning is CommandPlanWarning.HEAD_IGNORED_NON_URI:
            print(i18n.t(Keys.HEAD_IGNORED_NON_URI_WARNING))

    operation = plan.operation
    if plan.mode is CommandMode.PROVIDERS:
        return handle_providers_mode()
    if isinstance(operation, ConfigOperation):
        return handle_config_command(operation.action)
    if isinstance(operation, CollectOperation):
        return handle_collect_mode(operation)
    if isinstance(operation, StatsOperation):
        return handle_stats_mode(operation)
    if isinstance(operation, ReindexOperation):
        return handle_reindex_mode(operation)
    if plan.mode is CommandMode.HELP:
        parser.print_help()
        return None

    export_config = load_export_config()
    if isinstance(operation, UriOperation):
        return handle_uri_mode(operation, export_config=export_config)
    if isinstance(operation, SessionOperation):
        return handle_session_modes(operation, export_config=export_config)
    raise AssertionError(f"unhandled command mode: {plan.mode.value}")


if __name__ == "__main__":
    main()
