from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent_dump.command_plan import (
    CollectOperation,
    CommandMode,
    CommandPlanError,
    CommandPlanErrorCode,
    CommandPlanWarning,
    CommandRequest,
    SessionOperation,
    StatsOperation,
    UriOperation,
    build_command_plan,
)


def make_request(**overrides: Any) -> CommandRequest:
    return CommandRequest(**overrides)


@pytest.mark.parametrize(
    ("overrides", "expected_mode"),
    [
        ({"providers": True}, CommandMode.PROVIDERS),
        ({"config_action": "view"}, CommandMode.CONFIG),
        ({"collect": True}, CommandMode.COLLECT),
        ({"stats": True}, CommandMode.STATS),
        ({"reindex": True}, CommandMode.REINDEX),
        ({"uri": "codex://session"}, CommandMode.URI),
        ({"list_requested": True}, CommandMode.LIST),
        ({"search": "bug"}, CommandMode.LIST),
        ({"days": 3}, CommandMode.LIST),
        ({"query": "bug"}, CommandMode.LIST),
        ({"interactive": True}, CommandMode.INTERACTIVE),
        ({"days": 7}, CommandMode.LIST),
    ],
)
def test_build_command_plan_resolves_closed_operation_set(
    overrides: dict[str, object],
    expected_mode: CommandMode,
) -> None:
    plan = build_command_plan(make_request(**overrides))

    assert plan.mode is expected_mode


@pytest.mark.parametrize(
    ("overrides", "expected_mode", "ignored_options"),
    [
        (
            {"providers": True, "config_action": "view", "uri": "agents://.?providers=unknown"},
            CommandMode.PROVIDERS,
            ("--config", "agents:// query URI"),
        ),
        ({"config_action": "view", "collect": True}, CommandMode.CONFIG, ("--collect",)),
        ({"collect": True, "stats": True}, CommandMode.COLLECT, ("--stats",)),
        ({"stats": True, "reindex": True}, CommandMode.STATS, ("--reindex",)),
        ({"reindex": True, "uri": "codex://session"}, CommandMode.REINDEX, ("session URI",)),
        ({"uri": "codex://session", "list_requested": True}, CommandMode.URI, ("--list",)),
        ({"list_requested": True, "interactive": True}, CommandMode.LIST, ("--interactive",)),
    ],
)
def test_build_command_plan_preserves_mode_priority(
    overrides: dict[str, object],
    expected_mode: CommandMode,
    ignored_options: tuple[str, ...],
) -> None:
    plan = build_command_plan(make_request(**overrides))

    assert plan.mode is expected_mode
    assert plan.ignored_mode_options == ignored_options


def test_build_command_plan_does_not_warn_for_collect_query_uri() -> None:
    plan = build_command_plan(make_request(collect=True, uri="agents://.?providers=codex"))

    assert plan.ignored_mode_options == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"days": 0},
        {"days": -1},
        {"days": date.today().toordinal()},
        {"collect": True, "days": 0},
        {"stats": True, "days": 0},
        {"reindex": True, "days": 0},
    ],
)
def test_build_command_plan_rejects_days_outside_calendar_range(overrides: dict[str, object]) -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(make_request(**overrides))

    assert exc_info.value.code is CommandPlanErrorCode.DAYS_INVALID


def test_build_command_plan_normalizes_query_uri_once() -> None:
    cwd = Path("/tmp/project")

    plan = build_command_plan(
        make_request(uri="agents://.?q=bug&providers=codex&roles=user&limit=2"),
        cwd=cwd,
    )

    operation = plan.operation
    assert isinstance(operation, SessionOperation)
    assert operation.mode is CommandMode.LIST
    assert operation.days == 7
    assert operation.query_spec is not None
    assert operation.query_spec.keyword == "bug"
    assert operation.query_spec.agent_names == {"codex"}
    assert operation.query_spec.roles == {"user"}
    assert operation.query_spec.limit == 2
    assert operation.query_spec.project_path == cwd.resolve()


def test_build_command_plan_preserves_query_uri_in_explicit_interactive_mode() -> None:
    plan = build_command_plan(make_request(uri="agents://.", interactive=True))

    operation = plan.operation
    assert isinstance(operation, SessionOperation)
    assert operation.mode is CommandMode.INTERACTIVE
    assert operation.query_spec is not None


def test_build_command_plan_combines_search_with_query_scope() -> None:
    plan = build_command_plan(make_request(query="provider:codex role:user limit:4", search="auth timeout"))

    operation = plan.operation
    assert isinstance(operation, SessionOperation)
    assert operation.is_search is True
    assert operation.query_spec is not None
    assert operation.query_spec.keyword == "auth timeout"
    assert operation.query_spec.agent_names == {"codex"}
    assert operation.query_spec.roles == {"user"}
    assert operation.query_spec.limit == 4


def test_build_command_plan_normalizes_stats_query() -> None:
    plan = build_command_plan(make_request(stats=True, days=30, query="codex:bug"))

    operation = plan.operation
    assert isinstance(operation, StatsOperation)
    assert operation.days == 30
    assert operation.query_spec is not None
    assert operation.query_spec.agent_names == {"codex"}
    assert operation.query_spec.keyword == "bug"


def test_build_command_plan_normalizes_collect_query_uri() -> None:
    plan = build_command_plan(
        make_request(
            collect=True,
            uri="agents://.?providers=codex",
            days=30,
            since="2026-08-01",
            until="2026-08-10",
            save="report.md",
            dry_run=True,
            collect_mode="insight",
        )
    )

    operation = plan.operation
    assert isinstance(operation, CollectOperation)
    assert operation.days == 30
    assert operation.since == "2026-08-01"
    assert operation.until == "2026-08-10"
    assert operation.save == "report.md"
    assert operation.dry_run is True
    assert operation.collect_mode == "insight"
    assert operation.query_spec is not None
    assert operation.query_spec.agent_names == {"codex"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"collect": True, "uri": "codex://session"},
        {"collect": True, "list_requested": True},
        {"collect": True, "interactive": True},
    ],
)
def test_build_command_plan_rejects_collect_mode_conflicts(overrides: dict[str, object]) -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(make_request(**overrides))

    assert exc_info.value.code is CommandPlanErrorCode.COLLECT_MODE_CONFLICT


@pytest.mark.parametrize("overrides", [{"list_requested": True}, {"search": "bug"}, {"days": 3}, {"query": "bug"}])
def test_build_command_plan_allows_print_for_explicit_and_implicit_list(overrides: dict[str, object]) -> None:
    plan = build_command_plan(make_request(raw_format="print", format_specified=True, **overrides))

    operation = plan.operation
    assert isinstance(operation, SessionOperation)
    assert operation.output_formats == ("print",)


def test_build_command_plan_rejects_print_for_interactive() -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(make_request(raw_format="print", format_specified=True, interactive=True))

    assert exc_info.value.code is CommandPlanErrorCode.INTERACTIVE_PRINT


def test_build_command_plan_rejects_query_with_query_uri() -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(make_request(uri="agents://.", query="bug"))

    assert exc_info.value.code is CommandPlanErrorCode.QUERY_COMBINATION_INVALID


@pytest.mark.parametrize(
    ("command_request", "error_code"),
    [
        (make_request(uri="agents://.?providers=unknown"), CommandPlanErrorCode.QUERY_URI_INVALID),
        (make_request(list_requested=True, query="provider:unknown bug"), CommandPlanErrorCode.QUERY_SPEC_INVALID),
        (make_request(uri="not-a-uri"), CommandPlanErrorCode.URI_INVALID),
        (
            make_request(uri="codex://session", head=True, raw_format="json", format_specified=True),
            CommandPlanErrorCode.URI_HEAD_WITH_FORMAT,
        ),
        (make_request(uri="codex://session", head=True, summary=True), CommandPlanErrorCode.URI_HEAD_WITH_SUMMARY),
        (
            make_request(list_requested=True, raw_format="xml", format_specified=True),
            CommandPlanErrorCode.FORMAT_INVALID,
        ),
    ],
)
def test_build_command_plan_returns_structured_validation_errors(
    command_request: CommandRequest,
    error_code: CommandPlanErrorCode,
) -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(command_request)

    assert exc_info.value.code is error_code


def test_build_command_plan_normalizes_uri_modifiers() -> None:
    plan = build_command_plan(
        make_request(
            uri="codex://threads/session-1",
            output="exports",
            output_specified=True,
            raw_format="json,md",
            format_specified=True,
            summary=True,
        )
    )

    operation = plan.operation
    assert isinstance(operation, UriOperation)
    assert operation.raw_uri == "codex://threads/session-1"
    assert operation.scheme == "codex"
    assert operation.session_id == "session-1"
    assert operation.expected_agent_name == "codex"
    assert operation.output == "exports"
    assert operation.output_specified is True
    assert operation.output_formats == ("json", "markdown")
    assert operation.summary is True


def test_build_command_plan_records_non_uri_modifier_warnings() -> None:
    plan = build_command_plan(make_request(list_requested=True, summary=True, head=True))

    assert plan.warnings == (
        CommandPlanWarning.SUMMARY_IGNORED_NON_URI,
        CommandPlanWarning.HEAD_IGNORED_NON_URI,
    )
