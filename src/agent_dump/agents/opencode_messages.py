"""Translate OpenCode V2 projected messages into the shared transcript."""

import json
import sqlite3
from typing import Any

from agent_dump.agents.message_assembly import build_message, build_text_part, build_tool_part
from agent_dump.agents.message_types import MessageRole, NormalizedMessage, NormalizedPart, ToolPart
from agent_dump.coercion import safe_float, safe_int

_ROLES: dict[str, MessageRole] = {
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "skill": "system",
    "synthetic": "custom",
    "shell": "tool",
    "compaction": "compaction",
    "agent-switched": "custom",
    "model-switched": "custom",
    "location-switched": "custom",
    "idle": "custom",
}


def decode_message(row: sqlite3.Row) -> NormalizedMessage:
    """Decode one durable row, failing the read instead of hiding corrupt content."""
    try:
        data = json.loads(row["data"])
        if not isinstance(data, dict):
            raise ValueError("message data must be an object")
        return _build_message(row, data)
    except (ValueError, TypeError) as error:
        raise ValueError(f"Invalid OpenCode V2 message {row['id']}: {error}") from error


def _build_message(row: sqlite3.Row, data: dict[str, Any]) -> NormalizedMessage:
    kind = row["type"]
    timestamp = safe_int(row["time_created"])
    model = _object(data.get("model"))
    time = _object(data.get("time"))
    message = build_message(
        message_id=row["id"],
        role=_ROLES.get(kind, "unknown"),
        time_created=timestamp,
        time_completed=safe_int(time["completed"]) if time.get("completed") is not None else None,
        agent=data.get("agent") if isinstance(data.get("agent"), str) else None,
        model=model.get("id") if isinstance(model.get("id"), str) else None,
        provider=model.get("providerID") if isinstance(model.get("providerID"), str) else None,
        tokens=_object(data.get("tokens")),
        cost=safe_float(data.get("cost")),
        extra={"entry_type": kind},
        parts=[],
    )
    metadata = {key: value for key, value in data.items() if key not in {"text", "content"}}
    metadata["seq"] = row["seq"]
    message["metadata"] = metadata
    parts = message["parts"]
    if kind in {"user", "synthetic", "system", "skill"}:
        parts.append(build_text_part(_text(data, "text"), timestamp))
    elif kind == "assistant":
        unmapped = []
        for content in _objects(data.get("content")):
            part = _assistant_part(content, timestamp)
            if part is None:
                unmapped.append(content)
            else:
                parts.append(part)
        if unmapped:
            metadata["unmapped_content"] = unmapped
    elif kind == "shell":
        output = _object(data.get("output"))
        parts.append(
            build_tool_part(
                tool_name="shell",
                call_id=_text(data, "shellID"),
                title=_text(data, "command"),
                timestamp_ms=timestamp,
                state={
                    "status": data.get("status"),
                    "input": {"command": _text(data, "command")},
                    "output": output.get("output"),
                    "exit": data.get("exit"),
                    "truncated": output.get("truncated"),
                    "time": time,
                },
            )
        )
    elif kind == "compaction":
        for field in ("summary", "recent"):
            if field in data:
                parts.append(build_text_part(_text(data, field), timestamp))
    else:
        metadata.update(data)
    return message


def _assistant_part(content: dict[str, Any], timestamp: int) -> NormalizedPart | None:
    kind = _text(content, "type")
    if kind in ("text", "reasoning"):
        return build_text_part(_text(content, "text"), timestamp, kind)
    if kind == "tool":
        return _tool_part(content, timestamp)
    return None


def _tool_part(content: dict[str, Any], timestamp: int) -> ToolPart:
    state = content.get("state")
    if not isinstance(state, dict):
        raise ValueError("tool state must be an object")
    state = dict(state)
    _text(state, "status")
    if not isinstance(state.get("input"), (dict, str)):
        raise ValueError("tool input must be an object or streaming string")
    output = _objects(state.pop("content", []))
    for item in output:
        if item.get("type") == "text":
            _text(item, "text")
        elif item.get("type") == "file":
            _text(item, "uri")
    error = state.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        output.append({"type": "text", "text": error["message"]})
    if output:
        state["output"] = output
    state["time"] = _object(content.get("time"))
    for field in ("executed", "providerState", "providerResultState"):
        if field in content:
            state[field] = content[field]
    name = _text(content, "name")
    return build_tool_part(
        tool_name=name,
        call_id=_text(content, "id"),
        title=name,
        timestamp_ms=safe_int(state["time"].get("created", timestamp)),
        state=state,
    )


def _text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("content must be an array of objects")
    return list(value)
