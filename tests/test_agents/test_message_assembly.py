from agent_dump.agents.message_assembly import (
    backfill_tool_state,
    build_fallback_tool_message,
    build_message,
    build_text_part,
    build_tool_part,
)


def test_build_message_preserves_normalized_shape_and_extra():
    part = build_text_part("hello", 10, part_type="reasoning")

    message = build_message(
        message_id="message-1",
        role="assistant",
        parts=[part],
        time_created=10,
        agent="pi",
        mode="tool",
        model="gpt-5",
        provider="openai",
        extra={"entry_id": "entry-1"},
    )

    assert message == {
        "id": "message-1",
        "role": "assistant",
        "agent": "pi",
        "mode": "tool",
        "model": "gpt-5",
        "provider": "openai",
        "time_created": 10,
        "time_completed": None,
        "tokens": {},
        "cost": 0,
        "parts": [{"type": "reasoning", "text": "hello", "time_created": 10}],
        "entry_id": "entry-1",
    }


def test_build_tool_part_preserves_provider_state():
    state = {"input": {"path": "README.md"}, "output": None}

    part = build_tool_part(
        tool_name="read",
        call_id="call-1",
        title="read",
        state=state,
        timestamp_ms=20,
    )

    assert part == {
        "type": "tool",
        "tool": "read",
        "callID": "call-1",
        "title": "read",
        "state": state,
        "time_created": 20,
    }


def test_build_fallback_tool_message_handles_empty_and_unmatched_output():
    assert build_fallback_tool_message(message_id="message-1", output_parts=[]) is None

    message = build_fallback_tool_message(
        message_id="message-2",
        output_parts=[build_text_part("output", 30)],
        time_created=30,
        tool_call_id="call-2",
    )

    assert message is not None
    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call-2"
    assert message["parts"] == [{"type": "text", "text": "output", "time_created": 30}]


def test_backfill_tool_state_merges_output_and_state_updates():
    tool_part = build_tool_part(
        tool_name="read",
        call_id="call-1",
        title="read",
        state={"output": "legacy"},
        timestamp_ms=10,
    )
    messages = [build_message(message_id="message-1", role="assistant", parts=[tool_part])]
    pending_tool_calls = {"call-1": (0, 0)}

    updated_part = backfill_tool_state(
        messages,
        pending_tool_calls,
        call_id="call-1",
        output_parts=[build_text_part("first", 20)],
        state_updates={"status": "completed"},
    )
    backfill_tool_state(
        messages,
        pending_tool_calls,
        call_id="call-1",
        output_parts=[build_text_part("second", 30)],
    )

    assert updated_part is tool_part
    assert tool_part["state"] == {
        "output": [
            "legacy",
            {"type": "text", "text": "first", "time_created": 20},
            {"type": "text", "text": "second", "time_created": 30},
        ],
        "status": "completed",
    }
    assert (
        backfill_tool_state(
            messages,
            pending_tool_calls,
            call_id="missing",
            output_parts=[build_text_part("ignored")],
        )
        is None
    )
