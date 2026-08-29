from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent_dump.collect_models import CollectMode
from agent_dump.command_plan import (
    CollectOperation,
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
    StatsOperation,
    UriOperation,
    build_command_plan,
)
from agent_dump.query_semantics import TextQueryMode


def make_request(**overrides: Any) -> CommandRequest:
    return CommandRequest(**overrides)


@pytest.mark.parametrize(
    ("overrides", "expected_operation_type"),
    [
        ({"providers": True}, ProvidersOperation),
        ({"config_action": "view"}, ConfigOperation),
        ({"collect": True}, CollectOperation),
        ({"stats": True}, StatsOperation),
        ({"reindex": True}, ReindexOperation),
        ({"uri": "codex://session"}, UriOperation),
        ({"list_requested": True}, ListOperation),
        ({"search": "bug"}, SearchOperation),
        ({"days": 3}, ListOperation),
        ({"query": "bug"}, ListOperation),
        ({"interactive": True}, InteractiveOperation),
        ({"days": 7}, ListOperation),
        ({}, HelpOperation),
    ],
)
def test_build_command_plan_resolves_closed_operation_set(
    overrides: dict[str, object],
    expected_operation_type: type[object],
) -> None:
    plan = build_command_plan(make_request(**overrides))

    assert isinstance(plan.operation, expected_operation_type)


@pytest.mark.parametrize(
    ("overrides", "expected_operation_type", "ignored_options"),
    [
        (
            {"providers": True, "config_action": "view", "uri": "agents://.?providers=unknown"},
            ProvidersOperation,
            ("--config", "agents:// query URI"),
        ),
        ({"config_action": "view", "collect": True}, ConfigOperation, ("--collect",)),
        ({"config_action": "view", "uri": "agents://"}, ConfigOperation, ("agents:// query URI",)),
        ({"collect": True, "stats": True}, CollectOperation, ("--stats",)),
        ({"stats": True, "uri": "agents://"}, StatsOperation, ("agents:// query URI",)),
        ({"stats": True, "reindex": True}, StatsOperation, ("--reindex",)),
        ({"reindex": True, "uri": "agents://"}, ReindexOperation, ("agents:// query URI",)),
        ({"reindex": True, "uri": "codex://session"}, ReindexOperation, ("session URI",)),
        ({"uri": "codex://session", "list_requested": True}, UriOperation, ("--list",)),
        ({"list_requested": True, "interactive": True}, ListOperation, ("--interactive",)),
    ],
)
def test_build_command_plan_preserves_mode_priority(
    overrides: dict[str, object],
    expected_operation_type: type[object],
    ignored_options: tuple[str, ...],
) -> None:
    plan = build_command_plan(make_request(**overrides))

    assert isinstance(plan.operation, expected_operation_type)
    assert plan.ignored_mode_options == ignored_options


def test_build_command_plan_orders_and_reports_all_explicit_mode_candidates() -> None:
    plan = build_command_plan(
        make_request(
            providers=True,
            config_action="view",
            collect=True,
            stats=True,
            reindex=True,
            uri="codex://session",
            search="bug",
            list_requested=True,
            interactive=True,
        )
    )

    assert isinstance(plan.operation, ProvidersOperation)
    assert plan.ignored_mode_options == (
        "--config",
        "--collect",
        "--stats",
        "--reindex",
        "session URI",
        "--search",
        "--list",
        "--interactive",
    )


def test_build_command_plan_does_not_report_selectors_for_the_same_mode() -> None:
    plan = build_command_plan(make_request(uri="agents://.?providers=codex", search="bug", list_requested=True))

    assert isinstance(plan.operation, SearchOperation)
    assert plan.ignored_mode_options == ()


def test_build_command_plan_does_not_report_implicit_list_inputs_as_ignored() -> None:
    plan = build_command_plan(make_request(interactive=True, days=30, query="bug"))

    assert isinstance(plan.operation, InteractiveOperation)
    assert plan.ignored_mode_options == ()


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
    assert isinstance(operation, ListOperation)
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
    assert isinstance(operation, InteractiveOperation)
    assert operation.query_spec is not None


def test_build_command_plan_combines_search_with_query_scope() -> None:
    plan = build_command_plan(make_request(query="provider:codex role:user limit:4", search="auth timeout"))

    operation = plan.operation
    assert isinstance(operation, SearchOperation)
    assert operation.query_spec.keyword == "auth timeout"
    assert operation.query_spec.agent_names == {"codex"}
    assert operation.query_spec.roles == {"user"}
    assert operation.query_spec.limit == 4
    assert operation.query_spec.text_mode is TextQueryMode.SEARCH_TERMS


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
            collect_mode=CollectMode.INSIGHT,
        )
    )

    operation = plan.operation
    assert isinstance(operation, CollectOperation)
    assert operation.days == 30
    assert operation.since == "2026-08-01"
    assert operation.until == "2026-08-10"
    assert operation.save == "report.md"
    assert operation.dry_run is True
    assert operation.collect_mode is CollectMode.INSIGHT
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
    plan = build_command_plan(make_request(raw_format="print", **overrides))

    operation = plan.operation
    assert isinstance(operation, (ListOperation, SearchOperation))


def test_build_command_plan_rejects_print_for_interactive() -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(make_request(raw_format="print", interactive=True))

    assert exc_info.value.code is CommandPlanErrorCode.INTERACTIVE_PRINT


def test_build_command_plan_rejects_query_with_query_uri() -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(make_request(uri="agents://.", query="bug"))

    assert exc_info.value.code is CommandPlanErrorCode.QUERY_COMBINATION_INVALID


@pytest.mark.parametrize(
    ("command_request", "error_code"),
    [
        (make_request(uri="agents://.?providers=unknown"), CommandPlanErrorCode.QUERY_URI_INVALID),
        (make_request(uri="agents://.?providres=codex"), CommandPlanErrorCode.QUERY_URI_INVALID),
        (make_request(uri="agents://.?q=bug&q=secret"), CommandPlanErrorCode.QUERY_URI_INVALID),
        (make_request(list_requested=True, query="provider:unknown bug"), CommandPlanErrorCode.QUERY_SPEC_INVALID),
        (make_request(uri="not-a-uri"), CommandPlanErrorCode.URI_INVALID),
        (
            make_request(uri="codex://session", head=True, raw_format="json"),
            CommandPlanErrorCode.URI_HEAD_WITH_FORMAT,
        ),
        (make_request(uri="codex://session", head=True, summary=True), CommandPlanErrorCode.URI_HEAD_WITH_SUMMARY),
        (
            make_request(list_requested=True, raw_format="xml"),
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


def test_build_command_plan_rejects_explicit_empty_format() -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(make_request(list_requested=True, raw_format=""))

    assert exc_info.value.code is CommandPlanErrorCode.FORMAT_INVALID
