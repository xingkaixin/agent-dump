from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import ClassVar

from agent_dump.agent_registry import AGENT_REGISTRATIONS, get_uri_scheme_map
from agent_dump.collect_models import CollectMode
from agent_dump.output_formats import parse_format_spec, validate_formats_for_mode
from agent_dump.query_filter import QuerySpec, parse_query, parse_query_uri
from agent_dump.uri_support import parse_uri


class CommandMode(Enum):
    PROVIDERS = "providers"
    CONFIG = "config"
    COLLECT = "collect"
    STATS = "stats"
    REINDEX = "reindex"
    URI = "uri"
    LIST = "list"
    INTERACTIVE = "interactive"
    HELP = "help"


class CommandPlanErrorCode(Enum):
    QUERY_URI_INVALID = "query-uri-invalid"
    QUERY_SPEC_INVALID = "query-spec-invalid"
    QUERY_COMBINATION_INVALID = "query-combination-invalid"
    COLLECT_MODE_CONFLICT = "collect-mode-conflict"
    URI_INVALID = "uri-invalid"
    URI_HEAD_WITH_FORMAT = "uri-head-with-format"
    URI_HEAD_WITH_SUMMARY = "uri-head-with-summary"
    FORMAT_INVALID = "format-invalid"
    INTERACTIVE_PRINT = "interactive-print"
    DAYS_INVALID = "days-invalid"


class CommandPlanWarning(Enum):
    SUMMARY_IGNORED_NON_URI = "summary-ignored-non-uri"
    HEAD_IGNORED_NON_URI = "head-ignored-non-uri"


class CommandPlanError(ValueError):
    def __init__(self, code: CommandPlanErrorCode, *, detail: str | None = None) -> None:
        super().__init__(detail or code.value)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CommandRequest:
    uri: str | None = None
    days: int | None = None
    output: str | None = None
    raw_format: str | None = None
    output_specified: bool = False
    head: bool = False
    summary: bool = False
    collect: bool = False
    collect_mode: CollectMode = CollectMode.PM
    dry_run: bool = False
    stats: bool = False
    providers: bool = False
    reindex: bool = False
    config_action: str | None = None
    list_requested: bool = False
    interactive: bool = False
    no_metadata_summary: bool = False
    query: str | None = None
    search: str | None = None
    since: str | None = None
    until: str | None = None
    save: str | None = None


@dataclass(frozen=True)
class ProvidersOperation:
    mode: ClassVar[CommandMode] = CommandMode.PROVIDERS


@dataclass(frozen=True)
class ConfigOperation:
    action: str
    mode: ClassVar[CommandMode] = CommandMode.CONFIG


@dataclass(frozen=True)
class CollectOperation:
    days: int | None
    since: str | None
    until: str | None
    save: str | None
    dry_run: bool
    collect_mode: CollectMode
    query_spec: QuerySpec | None
    mode: ClassVar[CommandMode] = CommandMode.COLLECT


@dataclass(frozen=True)
class StatsOperation:
    days: int
    query_spec: QuerySpec | None
    mode: ClassVar[CommandMode] = CommandMode.STATS


@dataclass(frozen=True)
class ReindexOperation:
    days: int
    mode: ClassVar[CommandMode] = CommandMode.REINDEX


@dataclass(frozen=True)
class UriOperation:
    raw_uri: str
    scheme: str
    session_id: str
    expected_agent_name: str
    output: str | None
    output_specified: bool
    output_formats: tuple[str, ...]
    head: bool
    summary: bool
    mode: ClassVar[CommandMode] = CommandMode.URI


@dataclass(frozen=True)
class SessionOperation:
    mode: CommandMode
    days: int
    query_spec: QuerySpec | None
    is_search: bool
    output: str | None
    output_specified: bool
    format_specified: bool
    output_formats: tuple[str, ...]
    show_metadata_summary: bool

    def __post_init__(self) -> None:
        if self.mode not in {CommandMode.LIST, CommandMode.INTERACTIVE}:
            raise ValueError(f"invalid session mode: {self.mode.value}")


@dataclass(frozen=True)
class HelpOperation:
    mode: ClassVar[CommandMode] = CommandMode.HELP


CommandOperation = (
    ProvidersOperation
    | ConfigOperation
    | CollectOperation
    | StatsOperation
    | ReindexOperation
    | UriOperation
    | SessionOperation
    | HelpOperation
)


@dataclass(frozen=True)
class CommandPlan:
    operation: CommandOperation
    warnings: tuple[CommandPlanWarning, ...] = ()
    ignored_mode_options: tuple[str, ...] = ()

    @property
    def mode(self) -> CommandMode:
        return self.operation.mode


@dataclass(frozen=True)
class _ModeCandidate:
    mode: CommandMode
    ignored_label: str | None = None


_VALID_AGENT_NAMES = {registration.name for registration in AGENT_REGISTRATIONS}
_URI_SCHEME_TO_AGENT = get_uri_scheme_map()


def build_command_plan(
    request: CommandRequest,
    *,
    cwd: Path | None = None,
    valid_agents: set[str] | None = None,
) -> CommandPlan:
    is_query_uri = request.uri is not None and request.uri.startswith("agents://")
    mode_candidates = _build_mode_candidates(request, is_query_uri=is_query_uri)
    mode = mode_candidates[0].mode
    ignored_mode_options = tuple(
        candidate.ignored_label
        for candidate in mode_candidates
        if candidate.ignored_label is not None and candidate.mode is not mode
    )

    if mode is CommandMode.PROVIDERS:
        return CommandPlan(
            ProvidersOperation(),
            ignored_mode_options=ignored_mode_options,
        )

    effective_agents = valid_agents if valid_agents is not None else _VALID_AGENT_NAMES
    query_uri_spec = _parse_query_uri(request.uri, valid_agents=effective_agents, cwd=cwd)
    if request.query and query_uri_spec is not None:
        raise CommandPlanError(CommandPlanErrorCode.QUERY_COMBINATION_INVALID)

    operation = _build_operation(request, mode=mode, query_uri_spec=query_uri_spec, valid_agents=effective_agents)
    return CommandPlan(
        operation=operation,
        warnings=_build_warnings(request, mode=mode),
        ignored_mode_options=ignored_mode_options,
    )


def _build_mode_candidates(request: CommandRequest, *, is_query_uri: bool) -> tuple[_ModeCandidate, ...]:
    """Build all applicable modes once, in compatibility-priority order."""
    candidates: list[_ModeCandidate] = []
    if request.providers:
        candidates.append(_ModeCandidate(CommandMode.PROVIDERS, "--providers"))
    if request.config_action:
        candidates.append(_ModeCandidate(CommandMode.CONFIG, "--config"))
    if request.collect:
        candidates.append(_ModeCandidate(CommandMode.COLLECT, "--collect"))
    if request.stats:
        candidates.append(_ModeCandidate(CommandMode.STATS, "--stats"))
    if request.reindex:
        candidates.append(_ModeCandidate(CommandMode.REINDEX, "--reindex"))
    if request.uri and not is_query_uri:
        candidates.append(_ModeCandidate(CommandMode.URI, "session URI"))
    if request.search:
        candidates.append(_ModeCandidate(CommandMode.LIST, "--search"))
    if request.list_requested:
        candidates.append(_ModeCandidate(CommandMode.LIST, "--list"))
    if request.interactive:
        candidates.append(_ModeCandidate(CommandMode.INTERACTIVE, "--interactive"))
    if is_query_uri and not request.collect:
        candidates.append(_ModeCandidate(CommandMode.LIST, "agents:// query URI"))
    elif request.days is not None or request.query:
        candidates.append(_ModeCandidate(CommandMode.LIST))
    if not candidates:
        candidates.append(_ModeCandidate(CommandMode.HELP))
    return tuple(candidates)


def _parse_query_uri(
    raw_uri: str | None,
    *,
    valid_agents: set[str],
    cwd: Path | None,
) -> QuerySpec | None:
    if raw_uri is None or not raw_uri.startswith("agents://"):
        return None
    try:
        return parse_query_uri(raw_uri, valid_agents=valid_agents, cwd=cwd or Path.cwd())
    except ValueError as exc:
        raise CommandPlanError(CommandPlanErrorCode.QUERY_URI_INVALID, detail=str(exc)) from exc


def _build_operation(
    request: CommandRequest,
    *,
    mode: CommandMode,
    query_uri_spec: QuerySpec | None,
    valid_agents: set[str],
) -> CommandOperation:
    if mode is CommandMode.CONFIG:
        return ConfigOperation(action=request.config_action or "view")
    if mode is CommandMode.COLLECT:
        if request.interactive or request.list_requested or (request.uri and query_uri_spec is None):
            raise CommandPlanError(CommandPlanErrorCode.COLLECT_MODE_CONFLICT)
        return CollectOperation(
            days=None if request.days is None else _validate_days(request.days),
            since=request.since,
            until=request.until,
            save=request.save,
            dry_run=request.dry_run,
            collect_mode=request.collect_mode,
            query_spec=query_uri_spec,
        )
    if mode is CommandMode.STATS:
        return StatsOperation(
            days=_days_or_default(request.days), query_spec=_parse_stats_query(request.query, valid_agents)
        )
    if mode is CommandMode.REINDEX:
        return ReindexOperation(days=_days_or_default(request.days))
    if mode is CommandMode.URI:
        return _build_uri_operation(request)
    if mode in {CommandMode.LIST, CommandMode.INTERACTIVE}:
        return _build_session_operation(request, mode=mode, query_uri_spec=query_uri_spec, valid_agents=valid_agents)
    if mode is CommandMode.HELP:
        _resolve_output_formats(request, mode=mode)
        return HelpOperation()
    raise AssertionError(f"unsupported command mode: {mode.value}")


def _parse_stats_query(raw_query: str | None, valid_agents: set[str]) -> QuerySpec | None:
    if not raw_query:
        return None
    return _parse_query(raw_query, valid_agents)


def _parse_query(raw_query: str | None, valid_agents: set[str]) -> QuerySpec | None:
    try:
        return parse_query(raw_query, valid_agents=valid_agents)
    except ValueError as exc:
        raise CommandPlanError(CommandPlanErrorCode.QUERY_SPEC_INVALID, detail=str(exc)) from exc


def _build_uri_operation(request: CommandRequest) -> UriOperation:
    raw_uri = request.uri or ""
    if request.head:
        if request.raw_format is not None:
            raise CommandPlanError(CommandPlanErrorCode.URI_HEAD_WITH_FORMAT)
        if request.summary:
            raise CommandPlanError(CommandPlanErrorCode.URI_HEAD_WITH_SUMMARY)
        output_formats: tuple[str, ...] = ()
    else:
        output_formats = _resolve_output_formats(request, mode=CommandMode.URI)

    uri_result = parse_uri(raw_uri)
    if uri_result is None:
        raise CommandPlanError(CommandPlanErrorCode.URI_INVALID)
    scheme, session_id = uri_result
    return UriOperation(
        raw_uri=raw_uri,
        scheme=scheme,
        session_id=session_id,
        expected_agent_name=_URI_SCHEME_TO_AGENT[scheme],
        output=request.output,
        output_specified=request.output_specified,
        output_formats=output_formats,
        head=request.head,
        summary=request.summary,
    )


def _build_session_operation(
    request: CommandRequest,
    *,
    mode: CommandMode,
    query_uri_spec: QuerySpec | None,
    valid_agents: set[str],
) -> SessionOperation:
    output_formats = _resolve_output_formats(request, mode=mode)
    query_spec = query_uri_spec if query_uri_spec is not None else _parse_query(request.query, valid_agents)
    is_search = bool(request.search)
    if is_search:
        query_spec = QuerySpec(
            agent_names=query_spec.agent_names if query_spec else None,
            keyword=request.search,
            project_path=query_spec.project_path if query_spec else None,
            roles=query_spec.roles if query_spec else None,
            limit=query_spec.limit if query_spec else None,
        )
    return SessionOperation(
        mode=mode,
        days=_days_or_default(request.days),
        query_spec=query_spec,
        is_search=is_search,
        output=request.output,
        output_specified=request.output_specified,
        format_specified=request.raw_format is not None,
        output_formats=output_formats,
        show_metadata_summary=not request.no_metadata_summary,
    )


def _days_or_default(days: int | None) -> int:
    return 7 if days is None else _validate_days(days)


def _validate_days(days: int) -> int:
    if isinstance(days, bool) or days <= 0 or days >= date.today().toordinal():
        raise CommandPlanError(CommandPlanErrorCode.DAYS_INVALID)
    return days


def _resolve_output_formats(request: CommandRequest, *, mode: CommandMode) -> tuple[str, ...]:
    try:
        formats = (
            parse_format_spec(request.raw_format)
            if request.raw_format is not None
            else (["print"] if mode is CommandMode.URI else ["json"])
        )
    except ValueError as exc:
        raise CommandPlanError(CommandPlanErrorCode.FORMAT_INVALID, detail=str(exc)) from exc

    try:
        validate_formats_for_mode(
            formats,
            is_uri_mode=mode is CommandMode.URI,
            is_list_mode=mode is CommandMode.LIST,
        )
    except ValueError as exc:
        if str(exc) == CommandPlanErrorCode.INTERACTIVE_PRINT.value:
            raise CommandPlanError(CommandPlanErrorCode.INTERACTIVE_PRINT) from exc
        raise
    return tuple(formats)


def _build_warnings(request: CommandRequest, *, mode: CommandMode) -> tuple[CommandPlanWarning, ...]:
    if mode is CommandMode.URI:
        return ()
    warnings: list[CommandPlanWarning] = []
    if request.summary:
        warnings.append(CommandPlanWarning.SUMMARY_IGNORED_NON_URI)
    if request.head:
        warnings.append(CommandPlanWarning.HEAD_IGNORED_NON_URI)
    return tuple(warnings)
