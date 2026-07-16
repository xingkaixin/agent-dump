"""Shared builders for the normalized session message contract."""

from typing import Any


def build_message(
    *,
    message_id: str,
    role: str,
    parts: list[dict[str, Any]],
    time_created: int = 0,
    agent: str | None = None,
    mode: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = {
        "id": message_id,
        "role": role,
        "agent": agent,
        "mode": mode,
        "model": model,
        "provider": provider,
        "time_created": time_created,
        "time_completed": None,
        "tokens": {},
        "cost": 0,
        "parts": parts,
    }
    if extra:
        message.update(extra)
    return message


def build_text_part(text: str, timestamp_ms: int = 0, part_type: str = "text") -> dict[str, Any]:
    return {
        "type": part_type,
        "text": text,
        "time_created": timestamp_ms,
    }


def build_tool_part(
    *,
    tool_name: str,
    call_id: str,
    title: str,
    state: dict[str, Any],
    timestamp_ms: int,
) -> dict[str, Any]:
    return {
        "type": "tool",
        "tool": tool_name,
        "callID": call_id,
        "title": title,
        "state": state,
        "time_created": timestamp_ms,
    }


def build_fallback_tool_message(
    *,
    message_id: str,
    output_parts: list[dict[str, Any]],
    time_created: int = 0,
    tool_call_id: str | None = None,
) -> dict[str, Any] | None:
    if not output_parts:
        return None

    extra = {"tool_call_id": tool_call_id} if tool_call_id else None
    return build_message(
        message_id=message_id,
        role="tool",
        parts=output_parts,
        time_created=time_created,
        extra=extra,
    )


def backfill_tool_state(
    messages: list[dict[str, Any]],
    pending_tool_calls: dict[str, tuple[int, int]],
    *,
    call_id: str,
    output_parts: list[dict[str, Any]],
    state_updates: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not call_id or (not output_parts and not state_updates):
        return None

    location = pending_tool_calls.get(call_id)
    if location is None:
        return None

    message_index, part_index = location
    tool_part = messages[message_index]["parts"][part_index]
    state = tool_part.setdefault("state", {})
    if output_parts:
        existing_output = state.get("output")
        if isinstance(existing_output, list):
            existing_output.extend(output_parts)
        elif existing_output is None:
            state["output"] = list(output_parts)
        else:
            state["output"] = [existing_output, *output_parts]
    if state_updates:
        state.update(state_updates)
    return tool_part
