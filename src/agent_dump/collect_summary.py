"""Summary payload normalization, merging and JSON extraction for collect.

从 collect.py 拆出：这些函数只处理 LLM 摘要 payload 的形状，与事件提取、chunk 规划、
tree reduction 没有任何耦合。
"""

from collections.abc import Iterable
import json
import re
from typing import Any, cast

from agent_dump.collect_models import MAX_SUMMARY_ITEMS_PER_FIELD, SUMMARY_FIELDS, CollectMode, collect_fields_for


def normalize_text(value: str) -> str:
    """Collapse whitespace in one summary or event text value."""
    return re.sub(r"\s+", " ", value).strip()


SUMMARY_JSON_PATTERN = re.compile(r"```json\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


def build_summary_json_schema(mode: CollectMode = CollectMode.PM) -> dict[str, Any]:
    """Build the strict schema for one collect mode."""
    return build_summary_json_schema_for_fields(collect_fields_for(mode))


def build_summary_json_schema_for_fields(summary_fields: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Build the strict schema for an explicit summary field set."""
    fields = summary_fields if summary_fields is not None else SUMMARY_FIELDS
    return {
        "name": "collect_summary",
        "schema": {
            "type": "object",
            "properties": {field_name: {"type": "array", "items": {"type": "string"}} for field_name in fields},
            "required": list(fields),
            "additionalProperties": False,
        },
        "strict": True,
    }


def dedupe_preserve_order(values: Iterable[str], *, limit: int | None = MAX_SUMMARY_ITEMS_PER_FIELD) -> list[str]:
    """Normalize and deduplicate text values without changing their first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_text(value)
        if not normalized:
            continue
        lowered = normalized.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
        if limit is not None and len(result) >= limit:
            break
    return result


def empty_summary_payload(mode: CollectMode = CollectMode.PM) -> dict[str, list[str]]:
    """Create one empty structured summary payload."""
    return {field_name: [] for field_name in collect_fields_for(mode)}


def normalize_summary_payload(payload: dict[str, Any], *, mode: CollectMode = CollectMode.PM) -> dict[str, list[str]]:
    """Normalize unknown payload to the fixed summary schema."""
    fields = collect_fields_for(mode)
    normalized: dict[str, list[str]] = {field_name: [] for field_name in fields}
    for field_name in fields:
        raw_value = payload.get(field_name, [])
        values: list[str]
        if isinstance(raw_value, list):
            values = [str(item) for item in raw_value if str(item).strip()]
        elif isinstance(raw_value, str) and raw_value.strip():
            values = [raw_value]
        else:
            values = []
        normalized[field_name] = dedupe_preserve_order(values)
    return normalized


def merge_summary_payloads(
    payloads: Iterable[dict[str, list[str]]],
    *,
    max_items_per_field: int | None = MAX_SUMMARY_ITEMS_PER_FIELD,
    mode: CollectMode = CollectMode.PM,
) -> dict[str, list[str]]:
    """Merge structured summaries deterministically."""
    fields = collect_fields_for(mode)
    merged: dict[str, list[str]] = {field_name: [] for field_name in fields}
    for field_name in fields:
        items: list[str] = []
        for payload in payloads:
            items.extend(payload.get(field_name, []))
        merged[field_name] = dedupe_preserve_order(items, limit=max_items_per_field)
    return merged


def summary_payload_size(payload: dict[str, list[str]]) -> int:
    """Return the number of structured summary items across all fields."""
    return sum(len(items) for items in payload.values())


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first usable JSON object from a model response."""
    match = SUMMARY_JSON_PATTERN.search(text)
    candidates = [match.group(1)] if match else []
    candidates.append(text.strip())

    stripped = text.strip()
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidates.append(stripped[first_brace : last_brace + 1])

    decoder = json.JSONDecoder()
    decode_errors: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            loaded, _ = decoder.raw_decode(candidate.strip())
        except json.JSONDecodeError as exc:
            decode_errors.append(
                f"{exc.msg} at line {exc.lineno} column {exc.colno} char {exc.pos} of {len(candidate)}"
            )
            continue
        if isinstance(loaded, dict):
            return cast(dict[str, Any], loaded)
    details = "; ".join(dedupe_preserve_order(decode_errors, limit=3))
    if details:
        raise ValueError(f"response is not valid JSON object: {details}")
    raise ValueError("response is not valid JSON object")


def serialize_summary_payload(payload: dict[str, list[str]]) -> str:
    """Serialize one structured summary payload for an LLM data envelope."""
    return json.dumps(payload, ensure_ascii=False, indent=2)
