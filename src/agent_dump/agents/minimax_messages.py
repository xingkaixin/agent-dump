"""Decode MiniMax Code's durable display messages."""

import json
from typing import Any

from agent_dump.agents.message_assembly import build_message, build_text_part, build_tool_part, normalize_message_role
from agent_dump.agents.message_types import MessageRole, TextPartType
from agent_dump.coercion import safe_int

_TOOL_STATUSES = {1: "running", 2: "completed", 3: "error", 4: "pending", 5: "pending"}


def decode_message(row: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(row["data_json"])
    if not isinstance(data, dict) or data.get("msg_id") != row["msg_id"]:
        raise ValueError(f"Invalid MiniMax Code display message: {row['msg_id']}")
    timestamp = safe_int(row["created_at_ms"])
    role = _message_role(data, row.get("role"))
    message: dict[str, Any] = dict(
        build_message(
            message_id=row["msg_id"], role=role, parts=[], time_created=timestamp, tokens=_message_tokens(data)
        )
    )
    message["turn_id"] = row.get("turn_id")
    message["source"] = row.get("source")
    message["kind"] = data.get("kind")
    message["finish_reason"] = data.get("finish_reason")
    message["attachments"] = [_attachment(item) for item in _objects(data, "attachments")]
    if role not in {"user", "assistant", "tool"}:
        message["parts"] = [{"type": "minimax_event", "data": data, "time_created": timestamp}]
        return message
    parts = message["parts"]
    text_fields: tuple[tuple[str, TextPartType], ...] = (("thinking_content", "reasoning"), ("msg_content", "text"))
    for key, part_type in text_fields:
        text = data.get(key)
        if isinstance(text, str) and text:
            parts.append(build_text_part(text, timestamp, part_type))
        elif text is not None and not isinstance(text, str):
            raise ValueError(f"Invalid MiniMax Code {key}: {row['msg_id']}")
    for tool in _objects(data, "tool_calls"):
        name, call_id = tool.get("tool_name"), tool.get("tool_call_id")
        if not isinstance(name, str) or not isinstance(call_id, str):
            raise ValueError(f"Invalid MiniMax Code tool call: {row['msg_id']}")
        parts.append(
            build_tool_part(
                tool_name=name,
                call_id=call_id,
                title=name,
                timestamp_ms=timestamp,
                state={
                    "status": _TOOL_STATUSES.get(safe_int(tool.get("tool_call_status")), "unknown"),
                    "input": _json_value(tool.get("tool_call_args", tool.get("tool_call_args_delta"))),
                    "output": _json_value(tool.get("tool_call_result_data")),
                    "duration_ms": tool.get("tool_call_duration_ms"),
                },
            )
        )
    return message


def _message_role(data: dict[str, Any], row_role: Any) -> MessageRole:
    kind = data.get("kind")
    if isinstance(kind, str) and kind:
        return "compaction" if kind.startswith("compaction") else "custom"
    msg_type = data.get("msg_type")
    if msg_type == 3:
        return "system"
    if msg_type not in (None, 1, 2):
        return "unknown"
    role = normalize_message_role(data.get("role", row_role))
    text = data.get("msg_content")
    if role == "user" and isinstance(text, str) and text.lstrip().startswith("<permission-response>"):
        return "custom"
    return role


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _objects(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Invalid MiniMax Code {key}: {data['msg_id']}")
    return value


def _message_tokens(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {}
    tokens: dict[str, Any] = {}
    for source, target in (("input_tokens", "input"), ("output_tokens", "output"), ("total_tokens", "total")):
        if isinstance(value := usage.get(source), int) and not isinstance(value, bool) and value >= 0:
            tokens[target] = value
    cache = {}
    for source, target in (("cache_read", "read"), ("cache_write", "write")):
        if isinstance(value := usage.get(source), int) and not isinstance(value, bool) and value >= 0:
            cache[target] = value
    if cache:
        tokens["cache"] = cache
    return tokens


def _attachment(item: dict[str, Any]) -> dict[str, Any]:
    meta = value if isinstance(value := item.get("meta"), dict) else {}
    local = value if isinstance(value := item.get("local"), dict) else {}
    cloud = value if isinstance(value := item.get("cloud"), dict) else {}
    return {
        "name": meta.get("fileName") or item.get("file_name") or item.get("fileName"),
        "path": local.get("filePath") or item.get("file_path") or item.get("filePath"),
        "mime_type": meta.get("mimeType") or item.get("mime_type") or item.get("mimeType"),
        "type": meta.get("attachmentType") or item.get("type"),
        "size": meta.get("sizeBytes"),
        "url": cloud.get("url"),
        "asset_id": local.get("assetId") or item.get("asset_id") or item.get("assetId"),
    }
