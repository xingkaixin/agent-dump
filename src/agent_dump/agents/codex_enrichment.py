"""Codex-specific subagent and skill message enrichment."""

from abc import ABC, abstractmethod
import json
import re
from typing import Any

from agent_dump.agents.message_assembly import build_message, build_text_part

SKILL_NAME_PATTERN = re.compile(r"<name>\s*(.*?)\s*</name>", re.DOTALL)
SUBAGENT_NOTIFICATION_PATTERN = re.compile(r"<subagent_notification>\s*(.*?)\s*</subagent_notification>", re.DOTALL)


class CodexMessageEnrichmentMixin(ABC):
    """Enrich Codex messages with subagent and skill metadata."""

    @abstractmethod
    def _try_parse_json_string(self, value: Any) -> Any | None:
        raise NotImplementedError

    def _extract_subagent_prompt(self, arguments: Any) -> str:
        """Extract the visible subagent prompt from tool arguments."""
        if isinstance(arguments, dict):
            message = str(arguments.get("message", "")).strip()
            if message:
                return message
            return json.dumps(arguments, ensure_ascii=False, indent=2)
        if isinstance(arguments, str):
            return arguments
        return json.dumps(arguments, ensure_ascii=False, indent=2)

    def _extract_subagent_notification(self, text: str) -> dict[str, Any] | None:
        """Parse one subagent notification block from a user message."""
        match = SUBAGENT_NOTIFICATION_PATTERN.fullmatch(text.strip())
        if match is None:
            return None

        payload = self._try_parse_json_string(match.group(1))
        if not isinstance(payload, dict):
            return None

        agent_id = str(payload.get("agent_id", "")).strip()
        nickname = str(payload.get("nickname", "")).strip()
        status = payload.get("status")
        completed_text = ""
        if isinstance(status, dict):
            completed_text = str(status.get("completed", "")).strip()

        if not agent_id or not completed_text:
            return None

        return {
            "agent_id": agent_id,
            "nickname": nickname,
            "text": completed_text,
        }

    def _build_subagent_notification_message(
        self,
        *,
        message_id: str,
        timestamp_ms: int,
        notification: dict[str, Any],
        subagent_nicknames: dict[str, str],
    ) -> dict[str, Any]:
        """Build one assistant message from a subagent notification payload."""
        agent_id = str(notification.get("agent_id", "")).strip()
        nickname = str(notification.get("nickname", "")).strip() or subagent_nicknames.get(agent_id, "")
        if nickname:
            subagent_nicknames[agent_id] = nickname

        extra = {"subagent_id": agent_id}
        if nickname:
            extra["nickname"] = nickname

        return build_message(
            message_id=message_id,
            role="assistant",
            time_created=timestamp_ms,
            parts=[build_text_part(str(notification.get("text", "")), timestamp_ms)],
            extra=extra,
        )

    def _maybe_build_subagent_notification_message(
        self,
        *,
        message_id: str,
        timestamp_ms: int,
        role: str,
        parts: list[dict[str, Any]],
        subagent_nicknames: dict[str, str],
    ) -> dict[str, Any] | None:
        """Convert a user subagent notification into an assistant message when applicable."""
        if role != "user" or len(parts) != 1:
            return None

        part = parts[0]
        if part.get("type") != "text":
            return None

        notification = self._extract_subagent_notification(str(part.get("text", "")))
        if notification is None:
            return None

        return self._build_subagent_notification_message(
            message_id=message_id,
            timestamp_ms=timestamp_ms,
            notification=notification,
            subagent_nicknames=subagent_nicknames,
        )

    def _record_subagent_output(
        self,
        *,
        tool_part: dict[str, Any],
        output_parts: list[dict[str, Any]],
        raw_output: Any,
        call_id: str,
        subagent_call_map: dict[str, dict[str, str]],
        subagent_nicknames: dict[str, str],
    ) -> None:
        """Persist subagent metadata from function_call_output back onto the tool part."""
        if tool_part.get("tool") != "subagent":
            return

        state = tool_part.setdefault("state", {})
        arguments = state.get("arguments")
        prompt = self._extract_subagent_prompt(arguments)
        state["prompt"] = prompt

        parsed_output = self._try_parse_json_string(raw_output)
        if not isinstance(parsed_output, dict):
            return

        agent_id = str(parsed_output.get("agent_id", "")).strip()
        nickname = str(parsed_output.get("nickname", "")).strip()

        if agent_id or nickname:
            subagent_call_map[call_id] = {
                "agent_id": agent_id,
                "nickname": nickname,
            }
        if agent_id and nickname:
            subagent_nicknames[agent_id] = nickname

        if agent_id:
            tool_part["subagent_id"] = agent_id
        if nickname:
            tool_part["nickname"] = nickname

        if output_parts:
            state["output"] = list(output_parts)

    def _is_skill_wrapper_text(self, text: str) -> bool:
        """Whether text is a full skill wrapper payload."""
        stripped = text.strip()
        return stripped.startswith("<skill>") and stripped.endswith("</skill>")

    def _extract_skill_name_from_text(self, text: str) -> str | None:
        """Extract a skill name from a full skill wrapper payload."""
        if not self._is_skill_wrapper_text(text):
            return None

        match = SKILL_NAME_PATTERN.search(text)
        if match is None:
            return None

        name = match.group(1).strip()
        return name or None

    def _build_skill_tool_part(self, name: str, timestamp_ms: int, call_id: str) -> dict[str, Any]:
        """Build one tool part for a skill payload."""
        return {
            "type": "tool",
            "tool": "skill",
            "callID": call_id,
            "title": "skill",
            "state": {
                "status": "completed",
                "input": {"name": name},
                "output": None,
            },
            "time_created": timestamp_ms,
        }

    def _convert_skill_user_message_for_json_export(
        self, message: dict[str, Any], skill_index: int
    ) -> dict[str, Any] | None:
        """Convert one skill-shaped user message into an assistant tool message."""
        if message.get("role") != "user":
            return None

        parts = message.get("parts", [])
        if len(parts) != 1:
            return None

        part = parts[0]
        if part.get("type") != "text":
            return None

        text = str(part.get("text", ""))
        skill_name = self._extract_skill_name_from_text(text)
        if skill_name is None:
            return None

        return build_message(
            message_id=str(message.get("id", "")),
            role="assistant",
            time_created=int(message.get("time_created", 0)),
            mode="tool",
            parts=[
                self._build_skill_tool_part(
                    skill_name,
                    int(part.get("time_created", message.get("time_created", 0))),
                    f"skill:{skill_index}",
                )
            ],
        )

    def _transform_skill_messages_for_json_export(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert skill wrapper user messages only for Codex JSON export."""
        transformed_messages: list[dict[str, Any]] = []
        skill_index = 0

        for message in messages:
            converted = self._convert_skill_user_message_for_json_export(message, skill_index)
            if converted is None:
                transformed_messages.append(message)
                continue

            transformed_messages.append(converted)
            skill_index += 1

        return transformed_messages
