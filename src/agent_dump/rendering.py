"""Session rendering and export helpers."""

from collections.abc import Mapping
from datetime import datetime
import json
from pathlib import Path, PurePath
from typing import Any

from agent_dump.agents.base import BaseAgent, MessageCountCompleteness, Session
from agent_dump.export_paths import build_session_output_path
from agent_dump.i18n import Keys, i18n
from agent_dump.message_filter import should_filter_message_for_export
from agent_dump.output_formats import FileOutputFormat
from agent_dump.private_files import ensure_output_dir, write_private_text
from agent_dump.text_safety import safe_body_text, safe_display_text
from agent_dump.time_utils import to_local_datetime
from agent_dump.transcript import ToolCall, TranscriptMessage, read_messages

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
        # head 的字段值（标题、cwd、model）同样来自 provider payload，且每项占一行
        value = merged_head.get(key)
        if (
            key == "message_count"
            and not isinstance(value, int)
            and merged_head.get("message_count_completeness") == MessageCountCompleteness.UNKNOWN.value
        ):
            value = i18n.t(Keys.MESSAGE_COUNT_UNKNOWN)
        lines.append(f"- {label}: {safe_display_text(_normalize_head_value(value))}")

    return "\n".join(lines)


def render_session_text(uri: str, session_data: Mapping[str, Any]) -> str:
    """Render session data as formatted text."""
    lines = ["# Session Dump", "", f"- URI: `{safe_display_text(uri)}`", ""]
    msg_idx = 1

    def _append_section(display_role: str, contents: list[str]) -> None:
        nonlocal msg_idx
        if not contents:
            return
        lines.append(f"## {msg_idx}. {safe_display_text(display_role)}")
        lines.append("")
        for content in contents:
            if not content:
                continue
            # 该函数同时服务 URI print 与 markdown 导出，净化放这里覆盖两条出口
            lines.append(safe_body_text(content))
            lines.append("")
        msg_idx += 1

    def _extract_subagent_prompt(call: ToolCall) -> str:
        """Markdown 要展示可读的提示词，所以 prompt 缺失时回退到 arguments。

        这是渲染的产品策略，不是「这条消息里有什么」，所以留在这一层。
        """
        if call.prompt:
            return call.prompt

        arguments = call.arguments
        if isinstance(arguments, dict):
            prompt = str(arguments.get("message", "")).strip()
            if prompt:
                return prompt
            return json.dumps(arguments, ensure_ascii=False, indent=2)
        if isinstance(arguments, str):
            return arguments.strip()
        return ""

    def _append_subagent_sections(message: TranscriptMessage) -> None:
        """subagent 提示词此前在 tool role 与 assistant 两个分支各展开了一遍。"""
        for call in message.subagent_calls:
            display = f"Assistant ({call.nickname})" if call.nickname else "Assistant"
            prompt = _extract_subagent_prompt(call)
            if prompt:
                _append_section(display, [prompt])

    for message in read_messages(session_data):
        msg = message.raw
        role_normalized = message.role
        content_parts = list(message.texts)

        if should_filter_message_for_export(msg):
            continue

        if role_normalized == "user":
            display_role = "User"
        elif role_normalized == "assistant":
            display_role = "Assistant"
        else:
            display_role = str(msg.get("role", "unknown")).capitalize()

        if message.nickname and role_normalized == "assistant":
            display_role = f"Assistant ({message.nickname})"

        if role_normalized == "tool":
            _append_subagent_sections(message)
            continue

        if content_parts:
            _append_section(display_role, content_parts)

        if role_normalized != "assistant":
            continue

        _append_subagent_sections(message)

    return "\n".join(lines)


def export_session_markdown(uri: str, session_data: Mapping[str, Any], session_id: str, output_dir: Path) -> Path:
    """Export a single session to Markdown."""
    ensure_output_dir(output_dir)
    output_path = build_session_output_path(output_dir, session_id, ".md")
    return write_private_text(output_path, render_session_text(uri, session_data))


def get_session_export_path(
    agent: BaseAgent,
    session: Session,
    output_dir: Path,
    output_format: FileOutputFormat,
) -> Path:
    """Derive the path an in-tree exporter will use without writing it."""
    if output_format == "json":
        suffix = ".json"
    elif output_format == "markdown":
        suffix = ".md"
    elif output_format == "raw":
        raw_suffix = getattr(agent, "raw_export_suffix", None)
        suffix = raw_suffix if isinstance(raw_suffix, str) else ".raw.jsonl"
    else:
        raise ValueError(f"Unsupported export format: {output_format}")

    return build_session_output_path(output_dir, session.id, suffix)


def export_session_in_format(
    agent: BaseAgent,
    session: Session,
    output_dir: Path,
    output_format: FileOutputFormat,
    *,
    session_data: Mapping[str, Any] | None = None,
    session_uri: str | None = None,
    json_fields: dict[str, Any] | None = None,
) -> Path:
    """Export one session in the requested file format."""
    if output_format == "json":
        if json_fields:
            return agent.export_session_with_fields(session, output_dir, json_fields)
        return agent.export_session(session, output_dir)
    if output_format == "raw":
        return agent.export_raw_session(session, output_dir)
    if output_format == "markdown":
        effective_session_data = session_data if session_data is not None else agent.get_cached_session_data(session)
        effective_session_uri = session_uri if session_uri is not None else agent.get_session_uri(session)
        return export_session_markdown(effective_session_uri, effective_session_data, session.id, output_dir)

    raise ValueError(f"Unsupported export format: {output_format}")


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

    message_count = fields.get("message_count")
    if isinstance(message_count, int):
        parts.append(f"msgs={message_count}")
    elif fields.get("message_count_completeness") == MessageCountCompleteness.UNKNOWN.value:
        parts.append(f"msgs={i18n.t(Keys.MESSAGE_COUNT_UNKNOWN)}")

    updated_at = fields.get("updated_at")
    if isinstance(updated_at, str) and updated_at.strip():
        parts.append(f"updated={updated_at}")

    parts.append(f"uri={uri}")
    return " | ".join(parts)
