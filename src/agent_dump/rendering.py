"""Session rendering and export helpers."""

import json
from pathlib import Path
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.message_filter import get_text_content_parts, should_filter_message_for_export


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

    for msg in messages:
        role = msg.get("role", "unknown")
        role_normalized = str(role).lower()
        content_parts = get_text_content_parts(msg)

        if role_normalized == "tool":
            continue
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
            state = part.get("state", {})
            arguments = state.get("arguments")
            prompt = ""
            if isinstance(arguments, dict):
                prompt = str(arguments.get("message", "")).strip()
                if not prompt:
                    prompt = json.dumps(arguments, ensure_ascii=False, indent=2)
            elif isinstance(arguments, str):
                prompt = arguments.strip()

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
