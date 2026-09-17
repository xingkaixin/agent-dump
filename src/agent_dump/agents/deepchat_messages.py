"""Translate DeepChat's structured transcript and content fallback."""

import json
from typing import Any

from agent_dump.agents.message_assembly import (
    build_image_part,
    build_message,
    build_plan_part,
    build_text_part,
    build_tool_part,
    normalize_message_role,
)
from agent_dump.coercion import safe_int


def _parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _object(value: Any) -> dict[str, Any]:
    parsed = _parse_json(value)
    return parsed if isinstance(parsed, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def decode_message(
    row: dict[str, Any],
    *,
    user: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    files: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = _object(row.get("metadata"))
    timestamp = safe_int(row.get("created_at"))
    role = normalize_message_role(row.get("role"))
    message = dict(
        build_message(
            message_id=str(row["id"]),
            role="compaction" if metadata.get("messageType") == "compaction" else role,
            parts=[],
            time_created=timestamp,
            model=metadata.get("model"),
            provider=metadata.get("provider"),
            tokens={
                "input": safe_int(metadata.get("inputTokens")),
                "output": safe_int(metadata.get("outputTokens")),
                "cache": {
                    "read": safe_int(metadata.get("cachedInputTokens")),
                    "write": safe_int(metadata.get("cacheWriteInputTokens")),
                },
            },
        )
    )
    message["status"] = row.get("status")
    message["metadata"] = metadata
    if role == "user":
        content = _parse_json(row["content"])
        raw_user = content if isinstance(content, dict) else {"text": _text(content)}
        text = _text(user[0].get("text")) if user else _text(raw_user.get("text"))
        message["parts"] = [build_text_part(text, timestamp)] if text else []
        message["links"] = [link["url"] for link in links] if user else raw_user.get("links", [])
        attachments = files if user else raw_user.get("files", [])
        message["attachments"] = (
            [
                {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "mime_type": item.get("mime_type") or item.get("mimeType") or item.get("type"),
                    "size": item.get("size"),
                }
                for item in attachments
                if isinstance(item, dict)
            ]
            if isinstance(attachments, list)
            else []
        )
        return message

    content = [_structured_block(block) for block in blocks] if blocks else _parse_json(row["content"])
    if not isinstance(content, list) or any(not isinstance(block, dict) for block in content):
        raise ValueError(f"Invalid DeepChat assistant content: {row['id']}")
    message["parts"] = [_decode_block(block, timestamp) for block in content]
    return message


def _structured_block(row: dict[str, Any]) -> dict[str, Any]:
    extra = _object(row.get("extra_json"))
    return {
        "type": row["block_type"],
        "content": row.get("text_content"),
        "status": row.get("status"),
        "timestamp": extra.get("timestamp", row.get("updated_at")),
        "tool_call": {
            **_object(extra.get("toolCallExtra")),
            "id": row.get("tool_call_id"),
            "name": row.get("tool_name"),
            "params": row.get("tool_params"),
            "response": row.get("tool_response"),
        },
        "image_data": {"data": extra.get("imageData"), "mimeType": row.get("image_mime_type")},
        "action_type": row.get("action_type"),
        "extra": extra.get("extra"),
    }


def _decode_block(block: dict[str, Any], message_timestamp: int) -> dict[str, Any]:
    kind = block.get("type")
    timestamp = safe_int(block.get("timestamp"), default=message_timestamp)
    text = _text(block.get("content"))
    if kind in {"content", "reasoning_content", "error"}:
        return dict(build_text_part(text, timestamp, "reasoning" if kind == "reasoning_content" else "text"))
    if kind == "tool_call":
        tool = _object(block.get("tool_call"))
        status = {
            "success": "completed",
            "granted": "completed",
            "error": "error",
            "denied": "error",
            "pending": "pending",
            "loading": "running",
        }.get(_text(block.get("status")), "unknown")
        state = {
            "status": status,
            "input": _parse_json(tool.get("params")),
            "output": tool.get("response"),
        }
        if tool.get("mcpResult") is not None:
            state["mcp_result"] = tool["mcpResult"]
        return dict(
            build_tool_part(
                tool_name=_text(tool.get("name")),
                call_id=_text(tool.get("id")),
                title=_text(tool.get("name")),
                state=state,
                timestamp_ms=timestamp,
            )
        )
    if kind == "plan":
        return dict(
            build_plan_part(
                text=text, output=block.get("extra"), approval_status=_text(block.get("status")), timestamp_ms=timestamp
            )
        )
    if kind == "image":
        image = _object(block.get("image_data"))
        return dict(build_image_part(mime_type=image.get("mimeType"), data=image.get("data"), timestamp_ms=timestamp))
    return {"type": f"deepchat_{kind}", "data": block, "time_created": timestamp}
