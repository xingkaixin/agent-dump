"""Session rendering and export helpers."""

from datetime import datetime
import json
from pathlib import Path, PurePath
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.message_filter import get_text_content_parts, should_filter_message_for_export
from agent_dump.time_utils import to_local_datetime

HEAD_FIELDS = (
    ("URI", "uri"),
    ("Agent", "agent"),
    ("Title", "title"),
    ("Created", "created_at"),
    ("Updated", "updated_at"),
    ("CWD/Project", "cwd_or_project"),
    ("Model", "model"),
    ("Message Count", "message_count"),
    ("Subtargets", "subtargets"),
)


def _truncate_text(value: str, limit: int = 120) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _normalize_head_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return to_local_datetime(value).strftime("%Y-%m-%d %H:%M:%S %Z")
    if isinstance(value, list):
        items = [_truncate_text(str(item), limit=48) for item in value if str(item).strip()]
        return ", ".join(items[:5]) if items else "-"
    if isinstance(value, str):
        text = _truncate_text(value)
        return text if text else "-"
    return str(value)


def render_session_head(uri: str, session_head: dict[str, Any]) -> str:
    """Render lightweight session metadata for discovery."""
    lines = ["# Session Head", ""]
    merged_head = dict(session_head)
    merged_head["uri"] = uri

    for label, key in HEAD_FIELDS:
        lines.append(f"- {label}: {_normalize_head_value(merged_head.get(key))}")

    return "\n".join(lines)


def render_session_text(uri: str, session_data: dict[str, Any]) -> str:
    """Render session data as formatted text."""
    lines = ["# Session Dump", "", f"- URI: `{uri}`", ""]
    messages = session_data.get("messages", [])
    msg_idx = 1

    def _append_section(display_role: str, contents: list[str]) -> None:
        nonlocal msg_idx
        if not contents:
            return
        lines.append(f"## {msg_idx}. {display_role}")
        lines.append("")
        for content in contents:
            if not content:
                continue
            lines.append(content)
            lines.append("")
        msg_idx += 1

    def _extract_subagent_prompt(part: dict[str, Any]) -> str:
        state = part.get("state", {})
        prompt = str(state.get("prompt", "")).strip()
        if prompt:
            return prompt

        arguments = state.get("arguments")
        if isinstance(arguments, dict):
            prompt = str(arguments.get("message", "")).strip()
            if prompt:
                return prompt
            return json.dumps(arguments, ensure_ascii=False, indent=2)
        if isinstance(arguments, str):
            return arguments.strip()
        return ""

    for msg in messages:
        role = msg.get("role", "unknown")
        role_normalized = str(role).lower()
        content_parts = get_text_content_parts(msg)

        if should_filter_message_for_export(msg):
            continue

        if role_normalized == "user":
            display_role = "User"
        elif role_normalized == "assistant":
            display_role = "Assistant"
        else:
            display_role = str(role).capitalize()

        nickname = str(msg.get("nickname", "")).strip()
        if nickname and role_normalized == "assistant":
            display_role = f"Assistant ({nickname})"

        if role_normalized == "tool":
            parts = msg.get("parts", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict) or part.get("type") != "tool" or part.get("tool") != "subagent":
                    continue
                part_nickname = str(part.get("nickname", "")).strip()
                part_display_role = f"Assistant ({part_nickname})" if part_nickname else "Assistant"
                prompt = _extract_subagent_prompt(part)
                if prompt:
                    _append_section(part_display_role, [prompt])
            continue

        if content_parts:
            _append_section(display_role, content_parts)

        if role_normalized != "assistant":
            continue

        parts = msg.get("parts", [])
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool" or part.get("tool") != "subagent":
                continue

            part_nickname = str(part.get("nickname", "")).strip()
            part_display_role = f"Assistant ({part_nickname})" if part_nickname else "Assistant"
            prompt = _extract_subagent_prompt(part)
            if prompt:
                _append_section(part_display_role, [prompt])

    return "\n".join(lines)


def export_session_markdown(uri: str, session_data: dict[str, Any], session_id: str, output_dir: Path) -> Path:
    """Export a single session to Markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{session_id}.md"
    output_path.write_text(render_session_text(uri, session_data), encoding="utf-8")
    return output_path


def export_session_in_format(
    agent: BaseAgent,
    session: Session,
    output_dir: Path,
    output_format: str,
    *,
    session_data: dict[str, Any] | None = None,
    session_uri: str | None = None,
) -> Path:
    """Export one session in the requested file format."""
    if output_format == "json":
        return agent.export_session(session, output_dir)
    if output_format == "raw":
        return agent.export_raw_session(session, output_dir)
    if output_format == "markdown":
        effective_session_data = session_data if session_data is not None else agent.get_session_data(session)
        effective_session_uri = session_uri if session_uri is not None else agent.get_session_uri(session)
        return export_session_markdown(effective_session_uri, effective_session_data, session.id, output_dir)

    raise ValueError(f"Unsupported export format: {output_format}")


def apply_summary_to_json_export(output_path: Path, summary_markdown: str) -> None:
    """Inject summary markdown into exported JSON as top-level `summary`."""
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("exported JSON payload is not an object")
    payload["summary"] = summary_markdown
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate_summary_text(text: str, max_length: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_length:
        return stripped
    return stripped[: max_length - 3] + "..."


def _compact_location(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return normalized
    if "/" not in normalized and "\\" not in normalized:
        return normalized

    path = PurePath(normalized)
    parts = [part for part in path.parts if part not in {"", "/", "\\"} and part != path.anchor]
    if not parts:
        return normalized
    if len(parts) == 1:
        return parts[0]
    return "/".join(parts[-2:])


def format_session_metadata_summary(agent: BaseAgent, session: Session) -> str:
    """Render reduced session metadata in a consistent one-line summary."""
    fields = agent.get_session_summary_fields(session)
    uri = agent.get_session_uri(session)
    parts: list[str] = []

    location = fields.get("cwd_project")
    if isinstance(location, str) and location.strip():
        parts.append(f"cwd={_truncate_summary_text(_compact_location(location), 32)}")

    model = fields.get("model")
    if isinstance(model, str) and model.strip():
        parts.append(f"model={_truncate_summary_text(model, 24)}")

    branch = fields.get("branch")
    if isinstance(branch, str) and branch.strip():
        parts.append(f"branch={_truncate_summary_text(branch, 24)}")

    message_count = fields.get("message_count")
    if isinstance(message_count, int):
        parts.append(f"msgs={message_count}")

    updated_at = fields.get("updated_at")
    if isinstance(updated_at, str) and updated_at.strip():
        parts.append(f"updated={updated_at}")

    parts.append(f"uri={uri}")
    return " | ".join(parts)
