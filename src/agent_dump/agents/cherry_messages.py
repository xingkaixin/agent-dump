"""Translate Cherry Studio's persisted AI SDK message parts."""

import json
from typing import Any

from agent_dump.agents.message_assembly import build_message, build_text_part, build_tool_part, normalize_message_role
from agent_dump.coercion import safe_int


def json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("Expected a Cherry Studio JSON object")
    return parsed


def message_model(row: dict[str, Any]) -> tuple[str | None, str | None]:
    snapshot = json_object(row.get("message_snapshot"))
    model = json_object(snapshot.get("model"))
    if model.get("id"):
        return model["id"], model.get("provider")
    provider, separator, model_id = (row.get("model_id") or "").partition("::")
    return (model_id, provider) if separator else (provider or None, None)


def decode_message(row: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json_object(row["data"])
        parts = data.get("parts", [])
        if not isinstance(parts, list) or any(not isinstance(part, dict) for part in parts):
            raise ValueError("Expected message parts")
        stats = json_object(row.get("stats"))
        model, provider = message_model(row)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid Cherry Studio message: {row['id']}") from exc
    timestamp = safe_int(row.get("created_at"))
    cache = json_object(stats.get("inputTokenDetails"))
    message = dict(
        build_message(
            message_id=row["id"],
            role=normalize_message_role(row["role"]),
            parts=[],
            time_created=timestamp,
            model=model,
            provider=provider,
            tokens={
                "input": safe_int(stats.get("inputTokens")),
                "output": safe_int(stats.get("outputTokens")),
                "cache": {
                    "read": safe_int(cache.get("cacheReadTokens")),
                    "write": safe_int(cache.get("cacheWriteTokens")),
                },
            },
        )
    )
    message["status"] = row.get("status")
    message["costs"] = stats.get("costs", [])
    message["parts"] = [_decode_part(part, timestamp) for part in parts]
    return message


def _decode_part(part: dict[str, Any], timestamp: int) -> dict[str, Any]:
    kind = part.get("type", "unknown")
    if kind in {"text", "reasoning"}:
        return dict(build_text_part(part.get("text", ""), timestamp, kind))
    if kind == "dynamic-tool" or kind.startswith("tool-"):
        name = part.get("toolName") if kind == "dynamic-tool" else kind.removeprefix("tool-")
        status = {
            "input-streaming": "pending",
            "input-available": "running",
            "approval-requested": "pending",
            "approval-responded": "pending",
            "output-available": "completed",
            "output-error": "error",
            "output-denied": "error",
        }.get(part.get("state", ""), "unknown")
        return dict(
            build_tool_part(
                tool_name=name or "unknown",
                call_id=part.get("toolCallId", ""),
                title=name or "unknown",
                state={
                    "status": status,
                    "input": part.get("input"),
                    "output": part.get("output"),
                    "error": part.get("errorText"),
                    "approval": part.get("approval"),
                },
                timestamp_ms=timestamp,
            )
        )
    if kind in {"data-code", "data-translation", "data-error"}:
        data = json_object(part.get("data"))
        text = data.get("message" if kind == "data-error" else "content", "")
        return dict(build_text_part(text or "", timestamp))
    # Control events, compaction summaries and file references must not become collect dialogue.
    return {"type": f"cherry_{kind}", "data": part, "time_created": timestamp}
