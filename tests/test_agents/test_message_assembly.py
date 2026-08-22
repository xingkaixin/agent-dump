import pytest

from agent_dump.agents.jsonl_scan import parse_iso_timestamp_ms
from agent_dump.agents.message_assembly import (
    backfill_tool_state,
    build_fallback_tool_message,
    build_image_part,
    build_message,
    build_plan_part,
    build_step_part,
    build_text_part,
    build_tool_part,
    try_append_to_assistant_group,
)
from agent_dump.agents.message_types import NormalizedMessage, NormalizedPart


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


def test_specialized_part_builders_preserve_normalized_shapes():
    assert build_plan_part(text="ship it", output=None, approval_status="success", timestamp_ms=10) == {
        "type": "plan",
        "input": "ship it",
        "output": None,
        "approval_status": "success",
        "time_created": 10,
    }
    assert build_image_part(mime_type="image/png", data="encoded", timestamp_ms=20) == {
        "type": "image",
        "mime_type": "image/png",
        "data": "encoded",
        "time_created": 20,
    }
    assert build_step_part(
        part_type="step-start",
        timestamp_ms=30,
        reason="start",
        tokens=None,
        cost=0,
    ) == {
        "type": "step-start",
        "time_created": 30,
        "reason": "start",
        "tokens": None,
        "cost": 0,
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


def test_backfill_tool_state_rejects_non_tool_location():
    messages = [build_message(message_id="message-1", role="assistant", parts=[build_text_part("text")])]

    assert (
        backfill_tool_state(
            messages,
            {"call-1": (0, 0)},
            call_id="call-1",
            output_parts=[build_text_part("ignored")],
        )
        is None
    )


class TestTryAppendToAssistantGroup:
    """AD-139：codex 与 claudecode 之前各自维护一份这段判断。"""

    @staticmethod
    def _assistant(parts: list[NormalizedPart]) -> NormalizedMessage:
        return build_message(message_id="assistant", role="assistant", parts=list(parts))

    @staticmethod
    def _part(part_type: str, text: str | None = None) -> NormalizedPart:
        if part_type in {"text", "reasoning"}:
            return build_text_part(text or "", part_type=part_type)
        return build_tool_part(tool_name="test", call_id="call", title="test", state={}, timestamp_ms=0)

    def test_no_active_group_returns_none(self):
        assert (
            try_append_to_assistant_group(
                [], current_assistant_index=None, parts=(self._part("text"),), blocking_part_types=("tool",)
            )
            is None
        )

    def test_folds_into_an_unblocked_group(self):
        messages = [self._assistant([self._part("reasoning")])]

        folded = try_append_to_assistant_group(
            messages,
            current_assistant_index=0,
            parts=(self._part("text", "hi"),),
            blocking_part_types=("tool",),
        )

        assert folded == 0
        assert [p["type"] for p in messages[0]["parts"]] == ["reasoning", "text"]

    @pytest.mark.parametrize("blocker", ["text", "tool"])
    def test_a_blocking_part_forces_a_new_group(self, blocker):
        messages = [self._assistant([self._part(blocker)])]

        folded = try_append_to_assistant_group(
            messages,
            current_assistant_index=0,
            parts=(self._part("reasoning"),),
            blocking_part_types=("text", "tool"),
        )

        assert folded is None
        assert len(messages[0]["parts"]) == 1, "被阻塞时不得改动原消息"

    def test_identical_tail_part_is_not_duplicated(self):
        part = self._part("text", "same")
        messages = [self._assistant([part])]

        try_append_to_assistant_group(
            messages, current_assistant_index=0, parts=(self._part("text", "same"),), blocking_part_types=("tool",)
        )

        assert len(messages[0]["parts"]) == 1

    def test_on_message_runs_only_when_folding_succeeds(self):
        calls: list[NormalizedMessage] = []
        blocked = [self._assistant([self._part("tool")])]

        try_append_to_assistant_group(
            blocked,
            current_assistant_index=0,
            parts=(self._part("text"),),
            blocking_part_types=("tool",),
            on_message=calls.append,
        )
        assert calls == [], "未并入时不应执行后处理"

        open_group = [self._assistant([self._part("reasoning")])]
        try_append_to_assistant_group(
            open_group,
            current_assistant_index=0,
            parts=(self._part("text"),),
            blocking_part_types=("tool",),
            on_message=calls.append,
        )
        assert calls == [open_group[0]]

    def test_multiple_parts_are_all_appended(self):
        messages = [self._assistant([])]

        try_append_to_assistant_group(
            messages,
            current_assistant_index=0,
            parts=(self._part("text", "a"), self._part("text", "b")),
            blocking_part_types=("tool",),
        )

        assert [p["text"] for p in messages[0]["parts"]] == ["a", "b"]


class TestParseIsoTimestampMs:
    """AD-139：三份解析器合一，并修正 naive 时间戳被按本机时区解释的问题。"""

    def test_utc_with_z_suffix(self):
        assert parse_iso_timestamp_ms("2026-07-20T10:00:00Z") == 1784541600000

    def test_explicit_offset(self):
        assert parse_iso_timestamp_ms("2026-07-20T19:00:00+09:00") == 1784541600000

    def test_naive_is_read_as_utc_not_local_time(self):
        """codex/claudecode 之前直接对 naive datetime 调 .timestamp()，Python 会按本机
        时区解释，同一份数据在不同时区的机器上相差数小时。"""
        assert parse_iso_timestamp_ms("2026-07-20T10:00:00") == parse_iso_timestamp_ms("2026-07-20T10:00:00Z")

    def test_naive_result_is_independent_of_the_machine_timezone(self, monkeypatch):
        import time

        baseline = parse_iso_timestamp_ms("2026-07-20T10:00:00")
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        if hasattr(time, "tzset"):
            time.tzset()
        try:
            assert parse_iso_timestamp_ms("2026-07-20T10:00:00") == baseline
        finally:
            monkeypatch.undo()
            if hasattr(time, "tzset"):
                time.tzset()

    @pytest.mark.parametrize("value", ["", None, "   ", "not-a-timestamp", "2026-13-45T99:99:99Z", 0])
    def test_unusable_values_yield_zero(self, value):
        assert parse_iso_timestamp_ms(value) == 0

    def test_subsecond_precision_is_kept(self):
        assert parse_iso_timestamp_ms("2026-07-20T10:00:00.250Z") == 1784541600250
