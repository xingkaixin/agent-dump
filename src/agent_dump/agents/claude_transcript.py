from dataclasses import dataclass, field
from typing import Any

from agent_dump.agents.jsonl_scan import parse_iso_timestamp_ms
from agent_dump.agents.message_assembly import (
    backfill_tool_state,
    build_fallback_tool_message,
    build_message,
    build_text_part,
    build_tool_part,
    try_append_to_assistant_group,
)
from agent_dump.agents.message_types import NormalizedMessage, NormalizedPart
from agent_dump.coercion import safe_int


@dataclass
class _ClaudeTranscriptState:
    messages: list[NormalizedMessage] = field(default_factory=list)
    pending_tool_calls: dict[str, tuple[int, int]] = field(default_factory=dict)
    ignored_tool_call_ids: set[str] = field(default_factory=set)
    assistant_uuid_to_tool_calls: dict[str, list[str]] = field(default_factory=dict)
    current_assistant_index: int | None = None
    latest_assistant_text_index: int | None = None

    def reset_assistant_group(self) -> None:
        self.current_assistant_index = None
        self.latest_assistant_text_index = None


class ClaudeTranscriptDecoder:
    """Decode Claude JSONL records into normalized transcript messages."""

    def __init__(self) -> None:
        self._state = _ClaudeTranscriptState()

    @property
    def messages(self) -> list[NormalizedMessage]:
        return self._state.messages

    def append_record(self, data: dict[str, Any]) -> None:
        if data.get("isMeta") is True:
            return

        msg_type = data.get("type", "")
        if msg_type == "assistant":
            self._append_assistant_record(data)
            return
        if msg_type == "user":
            self._append_user_record(data)
            return
        if msg_type != "tool_result":
            return

        timestamp_ms = self._parse_timestamp_ms(data)
        msg = data.get("message", {})
        output_parts = self._normalize_tool_output(msg.get("content"), timestamp_ms)
        fallback_message = build_fallback_tool_message(
            message_id=str(data.get("uuid", "")),
            output_parts=output_parts,
            time_created=timestamp_ms,
        )
        if fallback_message:
            self._state.messages.append(fallback_message)
        self._state.reset_assistant_group()

    def token_totals(self) -> tuple[int, int]:
        input_tokens = 0
        output_tokens = 0
        for message in self._state.messages:
            tokens = message.get("tokens")
            if not isinstance(tokens, dict):
                continue
            input_tokens += safe_int(tokens.get("input_tokens"))
            output_tokens += safe_int(tokens.get("output_tokens"))
        return input_tokens, output_tokens

    def _parse_timestamp_ms(self, data: dict[str, Any]) -> int:
        return parse_iso_timestamp_ms(data.get("timestamp"))

    def _build_tool_part(self, part: dict[str, Any], timestamp_ms: int) -> NormalizedPart:
        tool_name = str(part.get("name", ""))
        return build_tool_part(
            tool_name=tool_name,
            call_id=str(part.get("id", "")),
            title=f"Tool: {tool_name}",
            state={"input": part.get("input", {}), "output": None},
            timestamp_ms=timestamp_ms,
        )

    def _normalize_tool_output(self, content: Any, timestamp_ms: int) -> list[NormalizedPart]:
        if isinstance(content, str):
            return [build_text_part(content, timestamp_ms)] if content.strip() else []
        if isinstance(content, list):
            parts: list[NormalizedPart] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text", item.get("content", "")))
                    if text.strip():
                        parts.append(build_text_part(text, timestamp_ms))
                elif isinstance(item, str) and item.strip():
                    parts.append(build_text_part(item, timestamp_ms))
            return parts
        if content is None:
            return []
        text = str(content)
        return [build_text_part(text, timestamp_ms)] if text.strip() else []

    def _normalize_user_text_parts(self, content: Any, timestamp_ms: int) -> list[NormalizedPart]:
        if isinstance(content, str):
            return [build_text_part(content, timestamp_ms)] if content.strip() else []
        if not isinstance(content, list):
            return []

        parts: list[NormalizedPart] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "tool_result":
                    continue
                text = str(item.get("text", ""))
                if text.strip():
                    parts.append(build_text_part(text, timestamp_ms))
            elif isinstance(item, str) and item.strip():
                parts.append(build_text_part(item, timestamp_ms))
        return parts

    def _apply_assistant_metadata(self, message: NormalizedMessage, msg: dict[str, Any]) -> None:
        model = msg.get("model")
        usage = msg.get("usage")
        if model and not message.get("model"):
            message["model"] = model
        if isinstance(usage, dict) and not message.get("tokens"):
            message["tokens"] = usage

    def _append_assistant_reasoning(
        self,
        *,
        message_id: str,
        msg: dict[str, Any],
        timestamp_ms: int,
        part: NormalizedPart,
    ) -> int:
        state = self._state
        folded = try_append_to_assistant_group(
            state.messages,
            current_assistant_index=state.current_assistant_index,
            parts=(part,),
            blocking_part_types=("text", "tool"),
            on_message=lambda existing: self._apply_assistant_metadata(existing, msg),
        )
        if folded is not None:
            return folded

        message = build_message(
            message_id=message_id,
            role="assistant",
            agent="claude",
            time_created=timestamp_ms,
            parts=[part],
        )
        self._apply_assistant_metadata(message, msg)
        state.messages.append(message)
        return len(state.messages) - 1

    def _append_assistant_text(
        self,
        *,
        message_id: str,
        msg: dict[str, Any],
        timestamp_ms: int,
        part: NormalizedPart,
    ) -> int:
        state = self._state
        folded = try_append_to_assistant_group(
            state.messages,
            current_assistant_index=state.current_assistant_index,
            parts=(part,),
            blocking_part_types=("tool",),
            on_message=lambda existing: self._apply_assistant_metadata(existing, msg),
        )
        if folded is not None:
            return folded

        message = build_message(
            message_id=message_id,
            role="assistant",
            agent="claude",
            time_created=timestamp_ms,
            parts=[part],
        )
        self._apply_assistant_metadata(message, msg)
        state.messages.append(message)
        return len(state.messages) - 1

    def _attach_tool_call(
        self,
        *,
        message_id: str,
        msg: dict[str, Any],
        timestamp_ms: int,
        tool_part: NormalizedPart,
    ) -> tuple[int, int]:
        state = self._state
        if state.latest_assistant_text_index is not None:
            message = state.messages[state.latest_assistant_text_index]
            message["parts"].append(tool_part)
            self._apply_assistant_metadata(message, msg)
            return state.latest_assistant_text_index, len(message["parts"]) - 1

        message = build_message(
            message_id=message_id,
            role="assistant",
            agent="claude",
            time_created=timestamp_ms,
            mode="tool",
            parts=[tool_part],
        )
        self._apply_assistant_metadata(message, msg)
        state.messages.append(message)
        return len(state.messages) - 1, 0

    def _extract_tool_state_updates(self, tool_use_result: Any) -> dict[str, Any]:
        if not isinstance(tool_use_result, dict):
            return {}

        updates: dict[str, Any] = {}
        success = tool_use_result.get("success")
        if isinstance(success, bool):
            updates["status"] = "success" if success else "error"
        command_name = tool_use_result.get("commandName")
        if command_name:
            updates["meta"] = {"commandName": command_name}
        return updates

    def _backfill_tool_output(
        self,
        *,
        call_id: str,
        output_parts: list[NormalizedPart],
        state_updates: dict[str, Any] | None = None,
    ) -> bool:
        state = self._state
        tool_part = backfill_tool_state(
            state.messages,
            state.pending_tool_calls,
            call_id=call_id,
            output_parts=output_parts,
            state_updates=state_updates,
        )
        if tool_part is None:
            return False
        tool_state = tool_part.setdefault("state", {})
        if output_parts and "status" not in tool_state:
            tool_state["status"] = "completed"
        return bool(output_parts or state_updates)

    def _resolve_tool_call_id(self, data: dict[str, Any], item: dict[str, Any]) -> str:
        tool_call_id = str(item.get("tool_use_id", "")).strip()
        if tool_call_id:
            return tool_call_id
        source_uuid = str(data.get("sourceToolAssistantUUID", "")).strip()
        if not source_uuid:
            return ""
        tool_call_ids = self._state.assistant_uuid_to_tool_calls.get(source_uuid, [])
        return tool_call_ids[0] if len(tool_call_ids) == 1 else ""

    def _append_assistant_record(self, data: dict[str, Any]) -> None:
        state = self._state
        msg = data.get("message", {})
        timestamp_ms = self._parse_timestamp_ms(data)
        raw_content = msg.get("content", [])
        tool_call_ids: list[str] = []

        if isinstance(raw_content, list):
            for item in raw_content:
                if not isinstance(item, dict):
                    continue
                part_type = item.get("type")
                message_id = str(data.get("uuid", ""))
                if part_type == "thinking":
                    text = str(item.get("thinking", ""))
                    if text.strip():
                        state.current_assistant_index = self._append_assistant_reasoning(
                            message_id=message_id,
                            msg=msg,
                            timestamp_ms=timestamp_ms,
                            part=build_text_part(text, timestamp_ms, part_type="reasoning"),
                        )
                    continue
                if part_type == "text":
                    text = str(item.get("text", ""))
                    if text.strip():
                        state.current_assistant_index = self._append_assistant_text(
                            message_id=message_id,
                            msg=msg,
                            timestamp_ms=timestamp_ms,
                            part=build_text_part(text, timestamp_ms),
                        )
                        state.latest_assistant_text_index = state.current_assistant_index
                    continue
                if part_type != "tool_use":
                    continue

                tool_name = str(item.get("name", "")).strip()
                tool_call_id = str(item.get("id", "")).strip()
                if tool_name == "TodoWrite" and tool_call_id:
                    state.ignored_tool_call_ids.add(tool_call_id)
                    continue

                message_index, part_index = self._attach_tool_call(
                    message_id=message_id,
                    msg=msg,
                    timestamp_ms=timestamp_ms,
                    tool_part=self._build_tool_part(item, timestamp_ms),
                )
                state.current_assistant_index = message_index
                if tool_call_id:
                    state.pending_tool_calls[tool_call_id] = (message_index, part_index)
                    tool_call_ids.append(tool_call_id)

        if tool_call_ids:
            state.assistant_uuid_to_tool_calls[str(data.get("uuid", ""))] = tool_call_ids

    def _append_user_record(self, data: dict[str, Any]) -> None:
        state = self._state
        msg = data.get("message", {})
        timestamp_ms = self._parse_timestamp_ms(data)
        content = msg.get("content", "")

        if isinstance(content, str):
            parts = self._normalize_user_text_parts(content, timestamp_ms)
            if not parts:
                return
            state.messages.append(
                build_message(
                    message_id=str(data.get("uuid", "")),
                    role="user",
                    time_created=timestamp_ms,
                    parts=parts,
                )
            )
            state.reset_assistant_group()
            return
        if not isinstance(content, list):
            state.reset_assistant_group()
            return

        visible_parts = self._normalize_user_text_parts(content, timestamp_ms)
        tool_state_updates = self._extract_tool_state_updates(data.get("toolUseResult"))
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue
            tool_call_id = self._resolve_tool_call_id(data, item)
            if tool_call_id and tool_call_id in state.ignored_tool_call_ids:
                continue

            output_parts = self._normalize_tool_output(item.get("content"), timestamp_ms)
            if self._backfill_tool_output(
                call_id=tool_call_id,
                output_parts=output_parts,
                state_updates=tool_state_updates,
            ):
                continue
            fallback_message = build_fallback_tool_message(
                message_id=str(data.get("uuid", "")),
                output_parts=output_parts,
                time_created=timestamp_ms,
                tool_call_id=tool_call_id or None,
            )
            if fallback_message:
                state.messages.append(fallback_message)

        if visible_parts:
            state.messages.append(
                build_message(
                    message_id=str(data.get("uuid", "")),
                    role="user",
                    time_created=timestamp_ms,
                    parts=visible_parts,
                )
            )
        state.reset_assistant_group()
