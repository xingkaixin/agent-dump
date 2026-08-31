"""
Command-line interface for agent-dump
"""

import argparse
from pathlib import Path
import sys

from agent_dump.__about__ import __version__
from agent_dump.agent_registry import get_supported_uri_examples
from agent_dump.cli_shared import (
    print_diagnostic as _print_diagnostic,
    uses_configured_export_output,
)
from agent_dump.collect_models import CollectMode
from agent_dump.collect_requests import request_structured_summary_from_llm, request_summary_from_llm
from agent_dump.collect_workflow import handle_collect_mode as _handle_collect_mode
from agent_dump.command_plan import (
    CollectOperation,
    CommandPlan,
    CommandPlanError,
    CommandPlanErrorCode,
    CommandPlanWarning,
    CommandRequest,
    ConfigOperation,
    HelpOperation,
    InteractiveOperation,
    ListOperation,
    ProvidersOperation,
    ReindexOperation,
    SearchOperation,
    SessionOperation,
    StatsOperation,
    UriOperation,
    build_command_plan,
)
from agent_dump.config import (
    ConfigurationParseError,
    ExportConfig,
    load_export_config,
    load_shortcuts_config,
)
from agent_dump.config_command import handle_config_command
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
from agent_dump.shortcut import (
    ShortcutErrorCode,
    ShortcutExpansionError,
    expand_shortcut_argv as _expand_shortcut_argv,
)
from agent_dump.terminal_output import configure_standard_stream_encoding, render_terminal_message
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


def expand_shortcut_argv(argv: list[str]) -> list[str]:
    """Expand configured shortcut preset into regular CLI argv."""
    if "--shortcut" not in argv:
        return argv
    return _expand_shortcut_argv(argv, load_shortcuts_config())


def _language_from_argv(argv: list[str]) -> str | None:
    language: str | None = None
    for index, arg in enumerate(argv):
        if arg == "--":
            break
        if arg == "--lang" and index + 1 < len(argv):
            language = argv[index + 1]
        elif arg.startswith("--lang="):
            language = arg.split("=", 1)[1]
    return language


def handle_collect_mode(operation: CollectOperation) -> int:
    """Handle `--collect` flow."""
    return _handle_collect_mode(
        operation,
        scanner_factory=AgentScanner,
        request_summary=request_summary_from_llm,
        request_structured_summary=request_structured_summary_from_llm,
    )


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


def _build_command_request(args: argparse.Namespace) -> CommandRequest:
    return CommandRequest(
        uri=args.uri,
        days=args.days,
        output=args.output,
        raw_format=args.format,
        output_specified=args.output is not None,
        head=args.head,
        summary=args.summary,
        collect=args.collect,
        collect_mode=CollectMode(args.collect_mode),
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


def _build_argument_parser() -> argparse.ArgumentParser:
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
        type=CollectMode,
        choices=tuple(CollectMode),
        default=CollectMode.PM,
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
    return parser


def _report_shortcut_error(exc: ShortcutExpansionError) -> int:
    if exc.code is ShortcutErrorCode.MISSING_NAME:
        print(i18n.t(Keys.SHORTCUT_MISSING_NAME))
        return 1
    if exc.code is ShortcutErrorCode.DATE_INVALID:
        print(i18n.t(Keys.SHORTCUT_DATE_INVALID))
        return 1
    if exc.code is ShortcutErrorCode.TEMPLATE_INVALID:
        print(i18n.t(Keys.SHORTCUT_TEMPLATE_INVALID))
        return 1
    if exc.code is ShortcutErrorCode.NOT_FOUND:
        print(render_terminal_message(Keys.SHORTCUT_NOT_FOUND, name=exc.shortcut_name or ""))
        return 1
    if exc.code is ShortcutErrorCode.ARGS_MISMATCH:
        print(
            render_terminal_message(
                Keys.SHORTCUT_ARGS_MISMATCH,
                name=exc.shortcut_name or "",
                expected=exc.expected,
                actual=exc.actual,
            )
        )
        return 1
    if exc.code is ShortcutErrorCode.UNKNOWN_VARIABLE:
        print(render_terminal_message(Keys.SHORTCUT_UNKNOWN_VARIABLE, name=exc.variable_name or ""))
        return 1
    raise exc


def _report_command_plan_error(
    exc: CommandPlanError,
    *,
    parser: argparse.ArgumentParser,
    request: CommandRequest,
) -> int:
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
    if exc.code is CommandPlanErrorCode.DAYS_INVALID:
        parser.error(i18n.t(Keys.CLI_DAYS_INVALID, value=request.days))
    _print_diagnostic(
        unsupported_capability(
            i18n.t(Keys.DIAG_PRINT_UNSUPPORTED_MODE),
            capability_gap=i18n.t(Keys.DIAG_PRINT_UNSUPPORTED_DETAIL),
            next_steps=(i18n.t(Keys.DIAG_STEP_DROP_PRINT),),
        )
    )
    return 1


def _report_command_plan_warnings(plan: CommandPlan) -> None:
    for warning in plan.warnings:
        if warning is CommandPlanWarning.SUMMARY_IGNORED_NON_URI:
            print(i18n.t(Keys.SUMMARY_IGNORED_NON_URI_WARNING))
        elif warning is CommandPlanWarning.HEAD_IGNORED_NON_URI:
            print(i18n.t(Keys.HEAD_IGNORED_NON_URI_WARNING))
    if plan.ignored_mode_options:
        print(
            render_terminal_message(
                Keys.CLI_MODE_OPTIONS_IGNORED_WARNING,
                options=", ".join(plan.ignored_mode_options),
            )
        )


def _dispatch_command_plan(plan: CommandPlan, parser: argparse.ArgumentParser) -> int | None:
    operation = plan.operation
    if isinstance(operation, ProvidersOperation):
        return handle_providers_mode()
    if isinstance(operation, ConfigOperation):
        return handle_config_command(operation.action)
    if isinstance(operation, CollectOperation):
        return handle_collect_mode(operation)
    if isinstance(operation, StatsOperation):
        return handle_stats_mode(operation)
    if isinstance(operation, ReindexOperation):
        return handle_reindex_mode(operation)
    if isinstance(operation, HelpOperation):
        parser.print_help()
        return None

    export_config = (
        load_export_config()
        if isinstance(operation, (InteractiveOperation, UriOperation))
        and uses_configured_export_output(
            output_specified=operation.output_specified,
            output_formats=operation.output_formats,
        )
        else ExportConfig()
    )
    if isinstance(operation, UriOperation):
        return handle_uri_mode(operation, export_config=export_config)
    if isinstance(operation, (ListOperation, SearchOperation, InteractiveOperation)):
        return handle_session_modes(operation, export_config=export_config)
    raise AssertionError(f"unhandled command operation: {type(operation).__name__}")


def main() -> int | None:
    """Main entry point.

    只在这里做顶层兜底：任何漏到最外层的异常都渲染成诊断块，而不是给用户一段
    traceback。SystemExit 必须原样放行，argparse 的 --help / -v / usage error
    依赖它。
    """
    try:
        configure_standard_stream_encoding(sys.platform, (sys.stdout, sys.stderr))
        return _run()
    except DiagnosticError as exc:
        _print_diagnostic(exc)
        return 1
    except ConfigurationParseError as exc:
        print(render_terminal_message(Keys.CONFIG_PARSE_INVALID, path=exc.path))
        return 1
    except Exception as exc:  # noqa: BLE001 - 顶层兜底，转成诊断后以退出码 1 结束
        _print_diagnostic(unexpected_failure(exc))
        return 1


def _run() -> int | None:
    """Parse arguments and dispatch to the selected mode."""

    raw_argv = sys.argv[1:]
    setup_i18n(_language_from_argv(raw_argv))
    try:
        argv = expand_shortcut_argv(raw_argv)
    except ShortcutExpansionError as exc:
        return _report_shortcut_error(exc)

    setup_i18n(_language_from_argv(argv))

    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    request = _build_command_request(args)

    try:
        plan = build_command_plan(request, cwd=Path.cwd())
    except CommandPlanError as exc:
        return _report_command_plan_error(exc, parser=parser, request=request)

    _report_command_plan_warnings(plan)
    return _dispatch_command_plan(plan, parser)


if __name__ == "__main__":
    main()
