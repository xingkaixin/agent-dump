"""Codex stream semantics exercised through both real command-line entry points."""

from copy import deepcopy

from cli_fixture import export_parity, message, record
import pytest

pytestmark = pytest.mark.differential


@pytest.mark.parametrize(
    "records",
    [
        [message("assistant", "<proposed_plan>Pending</proposed_plan>")],
        [
            message("assistant", "<proposed_plan>A</proposed_plan>"),
            message("assistant", "<proposed_plan>B</proposed_plan>"),
            message("user", "PLEASE IMPLEMENT THIS PLAN"),
        ],
        [message("assistant", "<proposed_plan>   </proposed_plan>"), message("user", "Keep this message")],
    ],
    ids=["unfinished", "replacement", "empty-plan-is-text"],
)
def test_plan_lifecycle(cli, records):
    export_parity(cli, records)


def test_unmarked_injected_context_keeps_the_request(cli):
    export_parity(
        cli,
        [
            message("user", "<skills_instructions>context</skills_instructions>\nPlease fix the bug."),
            message("assistant", "Reply"),
        ],
    )


@pytest.mark.parametrize(
    "body",
    [
        "invalid-json",
        "[]",
        '{"agent_id":"child"}',
        '{"status":{"completed":"done"}}',
        '{"agent_id":"one", "status":{"completed":""}}',
    ],
)
def test_invalid_subagent_notification_remains_text(cli, body):
    export_parity(cli, [message("user", f"<subagent_notification>{body}</subagent_notification>")])


@pytest.mark.parametrize(
    "event",
    [
        record("future_response", text="ignored by the reference"),
        record("message", role="user", content="not a list"),
        record("message", role="assistant", content=[None, "string", {"type": "input_text", "text": "wrong kind"}]),
        record("message", role="user", content=[{"type": "input_image", "image_url": "synthetic"}]),
        record(
            "message", role="user", content=[{"type": "input_text", "text": None}, {"type": "input_text", "text": True}]
        ),
        record("reasoning", summary=None),
        {"type": "response_item", "payload": None},
        {"type": "response_item", "payload": ["not an object"]},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "no duplicate"}},
        {"type": "event_msg", "payload": {"type": "agent_reasoning", "text": "no duplicate"}},
    ],
)
def test_unknown_nontext_and_malformed_nested_records_match_reference(cli, event):
    export_parity(cli, [message("user", "Before"), deepcopy(event), message("assistant", "After")])


def test_nonstandard_roles_are_normalized(cli):
    export_parity(cli, [message(role, "Visible") for role in ["custom", "compaction", "branch_summary", "other", None]])
