"""Codex stream semantics exercised through both real command-line entry points."""

from copy import deepcopy

from cli_fixture import call, export_parity, message, output, reasoning, record
import pytest


@pytest.mark.parametrize(
    "records",
    [
        [message("user", "Start"), message("assistant", "Running"), call(), output(), message("assistant", "Done")],
        [call(), output(), call(identity="two"), output("next", "two")],
        [
            message("assistant", "Running"),
            call(),
            call(identity="two"),
            output("second", "two"),
            output("first"),
            output("more"),
            message("assistant", "Done"),
            call(identity="three"),
        ],
        [reasoning(), call(), output(), message("assistant", "Done")],
        [message("assistant", "Text"), reasoning(), call(), output()],
        [
            message("assistant", "Text"),
            call(),
            message("user", "Interrupt"),
            output(),
            call(identity="two"),
            output("other", "two"),
        ],
        [output("orphan"), message("assistant", "Visible")],
        [call(identity=""), output("unmatched", "")],
        [call(arguments={"step": 1}), call(arguments={"step": 2}), output()],
        [
            reasoning(),
            reasoning(),
            message("assistant", "same"),
            message("assistant", "same"),
            call(),
            message("assistant", "same"),
        ],
    ],
    ids=[
        "normal",
        "fallback-calls",
        "interleaved-and-repeated-output",
        "reasoning-before-tool",
        "tool-after-new-reasoning",
        "user-boundary",
        "orphan",
        "empty-call-id",
        "duplicate-call-id",
        "grouping-and-dedup",
    ],
)
def test_tool_stream_assembly(cli, records):
    export_parity(cli, records)


@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize(
    "value",
    [
        "text",
        "",
        None,
        False,
        1.5,
        0.000001,
        1e20,
        {"numbers": [1e-7, 1e-5, 0.0001, 1e15, 1e16, -0.0]},
        {"z": [True, "中文"], "a": 2},
        ["one", {"two": 3}],
    ],
)
def test_tool_output_shapes(cli, value, custom):
    export_parity(cli, [call(custom=custom), output(value, custom=custom), output(value, "orphan", custom=custom)])


@pytest.mark.parametrize(
    "arguments", ['{"z": 1, "a": 2}', "not json", "null", "false", "[]", None, 0, ["hello"], {"path": "foo"}]
)
def test_tool_argument_normalization(cli, arguments):
    event = call(arguments=arguments)
    event["payload"]["arguments"] = arguments
    export_parity(cli, [event, output()])


@pytest.mark.parametrize(
    "value",
    [
        '{"output":"visible", "metadata": 123}',
        '{"output":null}',
        '{"output":{"z":1,"a":2}}',
        '"text"',
        "null",
        '{"z":1,"a":2}',
        {"output": "dict-kept"},
    ],
)
def test_custom_tool_output_prefers_decoded_output_field(cli, value):
    export_parity(cli, [call(custom=True), output(value, custom=True), output(value, "orphan", custom=True)])


@pytest.mark.parametrize(
    "response",
    [
        "PLEASE IMPLEMENT THIS PLAN\nThanks",
        "No, revise it",
        "请先缩小范围",
        "<instructions>Context</instructions>",
        "",
        "   ",
    ],
)
def test_plan_response_consumption(cli, response):
    export_parity(
        cli,
        [
            message("assistant", "before <proposed_plan>\nPlan\n</proposed_plan> after"),
            message("user", response),
            message("assistant", "Next"),
        ],
    )


@pytest.mark.parametrize(
    "records",
    [
        [message("assistant", "<proposed_plan>Pending</proposed_plan>")],
        [
            message("assistant", "<proposed_plan>A</proposed_plan>"),
            message("assistant", "<proposed_plan>B</proposed_plan>"),
            message("user", "PLEASE IMPLEMENT THIS PLAN"),
        ],
        [
            message("assistant", "<proposed_plan>A</proposed_plan>"),
            message("developer", "Instructions"),
            message("user", "Reject"),
        ],
        [
            message("assistant", "<proposed_plan>A</proposed_plan>"),
            reasoning(),
            call(),
            output(),
            message("user", "Reject"),
        ],
        [message("assistant", "<proposed_plan>   </proposed_plan>"), message("user", "Keep this message")],
    ],
    ids=["unfinished", "replacement", "developer-not-approval", "reasoning-tool-between", "empty-plan-is-text"],
)
def test_plan_lifecycle(cli, records):
    export_parity(cli, records)


CONTEXTS = [
    "Explain the XML <instructions> tag.",
    "Update the AGENTS.md instructions for example.",
    "```xml\n<instructions>example</instructions>\n```",
    "> <environment_context>quoted</environment_context>",
    "    <instructions>example XML</instructions>",
    "\t<instructions>example XML</instructions>",
    "<instructions>context</instructions>\n    <instructions>example XML</instructions>",
    "<environment_context>example",
    "<instructions>context</instructions>\nPlease fix the bug.",
    "<instructions>one</instructions>\nMy question\n<instructions>two</instructions>",
    "<environment_context>\n<cwd>/tmp</cwd>\n</environment_context>",
    "# AGENTS.md instructions for /workspace\n\n<INSTRUCTIONS>rules</INSTRUCTIONS>",
    "<instructions>rules</instructions>\n<environment_context>cwd</environment_context>",
    "<permissions instructions>rules</permissions instructions>",
    "<collaboration_mode>Default</collaboration_mode>",
    "<multi_agent_mode>disabled</multi_agent_mode>",
    "<recommended_plugins>plugins</recommended_plugins>\n# AGENTS.md instructions for /workspace\n\n<INSTRUCTIONS>rules</INSTRUCTIONS>\n<skills_instructions>skills</skills_instructions>\n<apps_instructions>apps</apps_instructions>\n<plugins_instructions>plugins</plugins_instructions>",
    "<skills_instructions>context</skills_instructions>\nPlease fix the bug.",
    "\r\n<instructions>one</instructions>\r\n \t\r\n<skills_instructions>two</skills_instructions>\n",
    "<instructions>mismatched</environment_context>",
]


@pytest.mark.parametrize("text", CONTEXTS)
def test_injected_context_and_ordinary_mentions(cli, text):
    export_parity(cli, [message("user", text), message("assistant", "Reply")])


def test_mixed_nontext_context_remains_user_input(cli):
    event = message("user", "<instructions>example</instructions>")
    event["payload"]["content"].append({"type": "input_image", "image_url": "synthetic"})
    export_parity(cli, [event])


@pytest.mark.parametrize("prompt", [{"message": "Review this"}, {"z": 1, "a": "中文"}, "plain prompt", 4, None])
def test_subagent_prompt_and_nickname(cli, prompt):
    event = call("spawn_agent", "spawn", arguments=prompt)
    event["payload"]["arguments"] = prompt
    notification = (
        '<subagent_notification>{"agent_id":"child", "status":{"completed":"Finished"}}</subagent_notification>'
    )
    export_parity(
        cli,
        [
            message("assistant", "Delegating"),
            event,
            output('{"agent_id":"child", "nickname":"Nova"}', "spawn"),
            message("user", notification),
        ],
    )


def test_multiple_subagents_keep_their_own_names(cli):
    export_parity(
        cli,
        [
            call("spawn_agent", "a", {"message": "A"}),
            output('{"agent_id":"one", "nickname":"Ada"}', "a"),
            call("spawn_agent", "b", {"message": "B"}),
            output('{"agent_id":"two", "nickname":"Bob"}', "b"),
            message(
                "user",
                '<subagent_notification>{"agent_id":"two", "status":{"completed":"B done"}}</subagent_notification>',
            ),
            message(
                "user",
                '<subagent_notification>{"agent_id":"one", "nickname":"Alice", "status":{"completed":"A done"}}</subagent_notification>',
            ),
            message(
                "user",
                '<subagent_notification>{"agent_id":"one", "status":{"completed":"A again"}}</subagent_notification>',
            ),
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


@pytest.mark.parametrize("formats", ["json,md,raw,print", "raw,markdown,print,json", " JSON,md,MD,raw,json,PRINT "])
def test_json_only_skill_and_wait_transform_does_not_leak(cli, formats):
    export_parity(
        cli,
        [
            call("wait_agent", "waiting", {"ids": ["child"]}),
            output("done", "waiting"),
            message("user", "<skill>\n<name>first</name>\ncontent\n</skill>"),
            message("user", "<skill>missing name</skill>"),
            message("user", "before <skill><name>keep as text</name></skill>"),
            message("user", "<skill><name>第二个</name></skill>"),
            message("assistant", "Visible"),
            call("wait_agent"),
            call("read_file", "read", {"path": "source.py"}),
        ],
        formats=formats,
    )


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


def test_multipart_plan_uses_the_reference_approval_boundary(cli):
    event = message("assistant", "<proposed_plan>Plan</proposed_plan>")
    event["payload"]["content"].append({"type": "output_text", "text": "Additional text"})
    export_parity(cli, [event, message("user", "PLEASE IMPLEMENT THIS PLAN")])


def test_tool_output_keeps_its_own_timestamp(cli):
    event = output()
    event["timestamp"] = "2026-01-15T12:00:02.123Z"
    export_parity(cli, [message("assistant", "Running"), call(), event])
