import argparse

import pytest

from agent_dump.command_plan import (
    CommandMode,
    CommandPlanError,
    CommandPlanErrorCode,
    build_command_plan,
)
from agent_dump.query_filter import QuerySpec


def make_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "collect": False,
        "config_action": None,
        "days": None,
        "format": None,
        "head": False,
        "interactive": False,
        "list": False,
        "query": None,
        "reindex": False,
        "search": None,
        "stats": False,
        "summary": False,
        "uri": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.mark.parametrize(
    ("overrides", "expected_mode"),
    [
        ({"list": True}, CommandMode.LIST),
        ({"search": "bug"}, CommandMode.LIST),
        ({"days": 3}, CommandMode.LIST),
        ({"query": "bug"}, CommandMode.LIST),
        ({"interactive": True}, CommandMode.INTERACTIVE),
        ({"days": 7}, CommandMode.HELP),
        ({"uri": "codex://session"}, CommandMode.URI),
        ({"collect": True}, CommandMode.COLLECT),
    ],
)
def test_build_command_plan_resolves_closed_operation_set(
    overrides: dict[str, object],
    expected_mode: CommandMode,
) -> None:
    plan = build_command_plan(make_args(**overrides), query_uri_spec=None, format_specified=False)

    assert plan.mode is expected_mode


def test_build_command_plan_treats_query_uri_as_list() -> None:
    query_uri_spec = QuerySpec(None, None, None, None, None)

    plan = build_command_plan(
        make_args(uri="agents://."),
        query_uri_spec=query_uri_spec,
        format_specified=False,
    )

    assert plan.mode is CommandMode.LIST
    assert plan.days == 7


def test_build_command_plan_preserves_explicit_query_uri_interactive_mode() -> None:
    query_uri_spec = QuerySpec(None, None, None, None, None)

    plan = build_command_plan(
        make_args(uri="agents://.", interactive=True),
        query_uri_spec=query_uri_spec,
        format_specified=False,
    )

    assert plan.mode is CommandMode.INTERACTIVE


@pytest.mark.parametrize("overrides", [{"list": True}, {"search": "bug"}, {"days": 3}, {"query": "bug"}])
def test_build_command_plan_allows_print_for_explicit_and_implicit_list(overrides: dict[str, object]) -> None:
    plan = build_command_plan(
        make_args(format="print", **overrides),
        query_uri_spec=None,
        format_specified=True,
    )

    assert plan.mode is CommandMode.LIST
    assert plan.output_formats == ("print",)


def test_build_command_plan_rejects_print_for_interactive() -> None:
    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(
            make_args(format="print", interactive=True),
            query_uri_spec=None,
            format_specified=True,
        )

    assert exc_info.value.code is CommandPlanErrorCode.INTERACTIVE_PRINT


def test_build_command_plan_rejects_query_with_query_uri() -> None:
    query_uri_spec = QuerySpec(None, None, None, None, None)

    with pytest.raises(CommandPlanError) as exc_info:
        build_command_plan(
            make_args(uri="agents://.", query="bug"),
            query_uri_spec=query_uri_spec,
            format_specified=False,
        )

    assert exc_info.value.code is CommandPlanErrorCode.QUERY_COMBINATION_INVALID
