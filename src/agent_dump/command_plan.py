import argparse
from dataclasses import dataclass
from enum import Enum

from agent_dump.cli_shared import resolve_effective_formats, validate_formats_for_mode
from agent_dump.query_filter import QuerySpec


class CommandMode(Enum):
    CONFIG = "config"
    COLLECT = "collect"
    STATS = "stats"
    REINDEX = "reindex"
    URI = "uri"
    LIST = "list"
    INTERACTIVE = "interactive"
    HELP = "help"


class CommandPlanErrorCode(Enum):
    QUERY_COMBINATION_INVALID = "query-combination-invalid"
    URI_HEAD_WITH_FORMAT = "uri-head-with-format"
    URI_HEAD_WITH_SUMMARY = "uri-head-with-summary"
    INTERACTIVE_PRINT = "interactive-print"


class CommandPlanError(ValueError):
    def __init__(self, code: CommandPlanErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True)
class CommandPlan:
    mode: CommandMode
    days: int | None
    output_formats: tuple[str, ...]

    @property
    def is_uri_mode(self) -> bool:
        return self.mode is CommandMode.URI

    @property
    def is_list_mode(self) -> bool:
        return self.mode is CommandMode.LIST


def build_command_plan(
    args: argparse.Namespace,
    *,
    query_uri_spec: QuerySpec | None,
    format_specified: bool,
) -> CommandPlan:
    is_query_uri = query_uri_spec is not None
    if args.query and is_query_uri:
        raise CommandPlanError(CommandPlanErrorCode.QUERY_COMBINATION_INVALID)

    mode = _resolve_command_mode(args, is_query_uri=is_query_uri)
    days = args.days if mode in {CommandMode.CONFIG, CommandMode.COLLECT} or args.days is not None else 7

    if mode in {CommandMode.CONFIG, CommandMode.COLLECT, CommandMode.STATS, CommandMode.REINDEX}:
        return CommandPlan(mode=mode, days=days, output_formats=())

    if mode is CommandMode.URI and args.head:
        if format_specified:
            raise CommandPlanError(CommandPlanErrorCode.URI_HEAD_WITH_FORMAT)
        if args.summary:
            raise CommandPlanError(CommandPlanErrorCode.URI_HEAD_WITH_SUMMARY)
        return CommandPlan(mode=mode, days=days, output_formats=())

    output_formats = resolve_effective_formats(
        args,
        is_uri_mode=mode is CommandMode.URI,
        format_specified=format_specified,
    )
    try:
        validate_formats_for_mode(
            output_formats,
            is_uri_mode=mode is CommandMode.URI,
            is_list_mode=mode is CommandMode.LIST,
        )
    except ValueError as exc:
        if str(exc) == CommandPlanErrorCode.INTERACTIVE_PRINT.value:
            raise CommandPlanError(CommandPlanErrorCode.INTERACTIVE_PRINT) from exc
        raise

    return CommandPlan(mode=mode, days=days, output_formats=tuple(output_formats))


def _resolve_command_mode(args: argparse.Namespace, *, is_query_uri: bool) -> CommandMode:
    if args.config_action:
        return CommandMode.CONFIG
    if args.collect:
        return CommandMode.COLLECT
    if args.stats:
        return CommandMode.STATS
    if args.reindex:
        return CommandMode.REINDEX
    if args.uri and not is_query_uri:
        return CommandMode.URI
    if args.search or args.list:
        return CommandMode.LIST
    if args.interactive:
        return CommandMode.INTERACTIVE
    if args.days not in {None, 7} or args.query or is_query_uri:
        return CommandMode.LIST
    return CommandMode.HELP
