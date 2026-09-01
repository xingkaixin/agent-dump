"""Codex response stream decoding."""

from dataclasses import dataclass, field
import json
import re
from typing import Any

from agent_dump.agents.codex_enrichment import CodexMessageEnrichmentMixin
from agent_dump.agents.codex_patch import parse_apply_patch_input
from agent_dump.agents.jsonl_scan import parse_iso_timestamp_ms
from agent_dump.agents.message_assembly import (
    backfill_tool_state,
    build_fallback_tool_message,
    build_message,
    build_plan_part,
    build_text_part,
    build_tool_part,
    message_has_part_type,
    normalize_message_role,
    try_append_to_assistant_group,
)
from agent_dump.agents.message_types import NormalizedMessage, NormalizedPart, is_plan_part

CODEX_TOOL_TITLE_MAP = {
    "exec_command": "bash",
    "apply_patch": "patch",
    "patch": "patch",
    "subagent": "subagent",
}
PROPOSED_PLAN_PATTERN = re.compile(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", re.DOTALL)
PLAN_APPROVAL_PREFIX = "PLEASE IMPLEMENT THIS PLAN"
_USER_CONTEXT_BLOCK = re.compile(
    r"(?:# AGENTS\.md instructions for [^\r\n]+\r?\n(?:[ \t]*\r?\n)*)?"
    r"<(?P<tag>instructions|skills_instructions|apps_instructions|plugins_instructions|recommended_plugins|"
    r"environment_context|permissions instructions|collaboration_mode|multi_agent_mode)>"
    r".*?</(?P=tag)>(?:[ \t]*\r?\n)*",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class _CodexAssemblyState:
    """Mutable state for one pass over a Codex response stream."""

    messages: list[NormalizedMessage] = field(default_factory=list)
    pending_tool_calls: dict[str, tuple[int, int]] = field(default_factory=dict)
    subagent_call_map: dict[str, dict[str, str]] = field(default_factory=dict)
    subagent_nicknames: dict[str, str] = field(default_factory=dict)
    current_assistant_index: int | None = None
    latest_assistant_text_index: int | None = None
    pending_plan_location: tuple[int, int] | None = None

    def clear_assistant_group(self) -> None:
        self.current_assistant_index = None
        self.latest_assistant_text_index = None


class CodexTranscriptDecoder(CodexMessageEnrichmentMixin):
    """Convert Codex response records into normalized messages."""

    @staticmethod
    def new_state() -> _CodexAssemblyState:
        return _CodexAssemblyState()

    def append_record(self, state: _CodexAssemblyState, data: dict[str, Any]) -> None:
        self._convert_record_to_messages(data=data, state=state)

    def finish(self, state: _CodexAssemblyState) -> list[NormalizedMessage]:
        self._finalize_pending_plan(state.messages, state.pending_plan_location)
        return state.messages

    def _parse_timestamp_ms(self, data: dict[str, Any]) -> int:
        """Parse record timestamp into milliseconds."""
        return parse_iso_timestamp_ms(data.get("timestamp"))

    def _map_tool_title(self, tool_name: str) -> str:
        """Map Codex tool names to unified short titles."""
        return CODEX_TOOL_TITLE_MAP.get(tool_name, tool_name)

    def _normalize_tool_arguments(self, arguments: Any) -> Any:
        """Normalize tool arguments while preserving non-JSON strings."""
        if not isinstance(arguments, str):
            return arguments

        parsed = self._try_parse_json_string(arguments)
        return parsed if parsed is not None else arguments

    def _normalize_tool_name(self, tool_name: str) -> str:
        """Normalize Codex tool names to unified export names."""
        if tool_name == "spawn_agent":
            return "subagent"
        return tool_name

    def _normalize_custom_tool_name(self, tool_name: str) -> str:
        """Normalize Codex custom tool names to unified export names."""
        return "patch" if tool_name == "apply_patch" else tool_name

    def _build_plan_part(self, plan_text: str, timestamp_ms: int) -> NormalizedPart:
        """Build one plan part."""
        return build_plan_part(text=plan_text, output=None, approval_status="fail", timestamp_ms=timestamp_ms)

    def _build_tool_part(
        self,
        *,
        tool_name: str,
        call_id: str,
        arguments: Any,
        timestamp_ms: int,
    ) -> NormalizedPart:
        """Build one unified tool part."""
        return build_tool_part(
            tool_name=tool_name,
            call_id=call_id,
            title=self._map_tool_title(tool_name),
            state={"arguments": arguments},
            timestamp_ms=timestamp_ms,
        )

    def _build_function_tool_part(self, payload: dict[str, Any], timestamp_ms: int) -> NormalizedPart:
        """Build one tool part from a function_call payload."""
        raw_tool_name = str(payload.get("name", ""))
        tool_name = self._normalize_tool_name(raw_tool_name)
        arguments = self._normalize_tool_arguments(payload.get("arguments", {}))
        return self._build_tool_part(
            tool_name=tool_name,
            call_id=str(payload.get("call_id", "")),
            arguments=arguments,
            timestamp_ms=timestamp_ms,
        )

    def _build_custom_tool_part(self, payload: dict[str, Any], timestamp_ms: int) -> NormalizedPart:
        """Build one tool part from a custom_tool_call payload."""
        raw_tool_name = str(payload.get("name", ""))
        tool_name = self._normalize_custom_tool_name(raw_tool_name)
        arguments = self._normalize_custom_tool_arguments(raw_tool_name, payload.get("input"))
        return self._build_tool_part(
            tool_name=tool_name,
            call_id=str(payload.get("call_id", "")),
            arguments=arguments,
            timestamp_ms=timestamp_ms,
        )

    def _normalize_custom_tool_arguments(self, tool_name: str, raw_input: Any) -> Any:
        """Normalize custom tool input."""
        if tool_name == "apply_patch":
            return parse_apply_patch_input(str(raw_input or ""))
        return raw_input

    def _normalize_output_parts(self, output: Any, timestamp_ms: int) -> list[NormalizedPart]:
        """Normalize tool output into text parts."""
        if output is None:
            return []
        if isinstance(output, str):
            return [build_text_part(output, timestamp_ms)]
        if isinstance(output, (dict, list)):
            return [build_text_part(json.dumps(output, ensure_ascii=False, indent=2), timestamp_ms)]
        return [build_text_part(str(output), timestamp_ms)]

    def _normalize_custom_tool_output(self, output: Any, timestamp_ms: int) -> list[NormalizedPart]:
        """Normalize custom tool output and prefer the user-facing output field."""
        parsed_output = self._try_parse_json_string(output)
        if isinstance(parsed_output, dict) and "output" in parsed_output:
            return self._normalize_output_parts(parsed_output["output"], timestamp_ms)
        return self._normalize_output_parts(parsed_output if parsed_output is not None else output, timestamp_ms)

    def _extract_proposed_plan_content(self, text: str) -> str | None:
        """Extract the inner content of a proposed plan block."""
        match = PROPOSED_PLAN_PATTERN.search(text)
        if match is None:
            return None

        plan_text = match.group(1).strip()
        return plan_text or None

    def _extract_message_content_parts(self, role: str, content: Any, timestamp_ms: int) -> list[NormalizedPart]:
        """Extract text parts from a response_item message payload."""
        if not isinstance(content, list):
            return []

        parts: list[NormalizedPart] = []
        is_assistant = role == "assistant"
        supported_types = {"output_text"} if is_assistant else {"input_text"}

        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type not in supported_types:
                continue
            text = str(item.get("text", ""))
            if is_assistant:
                plan_text = self._extract_proposed_plan_content(text)
                if plan_text is not None:
                    parts.append(self._build_plan_part(plan_text, timestamp_ms))
                    continue
            parts.append(build_text_part(text, timestamp_ms))

        return parts

    def _extract_reasoning_parts(self, payload: dict[str, Any], timestamp_ms: int) -> list[NormalizedPart]:
        """Extract reasoning summary text parts."""
        summary = payload.get("summary", [])
        if not isinstance(summary, list):
            return []

        parts: list[NormalizedPart] = []
        for item in summary:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "summary_text":
                continue
            parts.append(build_text_part(str(item.get("text", "")), timestamp_ms, part_type="reasoning"))
        return parts

    def _append_assistant_text_message(
        self,
        messages: list[NormalizedMessage],
        *,
        message_id: str,
        timestamp_ms: int,
        parts: list[NormalizedPart],
    ) -> int | None:
        """Append one assistant text message, deduplicating identical adjacent records."""
        if not parts:
            return None

        if (
            messages
            and messages[-1].get("role") == "assistant"
            and messages[-1].get("time_created") == timestamp_ms
            and messages[-1].get("parts") == parts
        ):
            return len(messages) - 1

        messages.append(
            build_message(
                message_id=message_id,
                role="assistant",
                agent="codex",
                time_created=timestamp_ms,
                parts=parts,
            )
        )
        return len(messages) - 1

    def _append_assistant_reasoning(
        self,
        messages: list[NormalizedMessage],
        *,
        message_id: str,
        timestamp_ms: int,
        parts: list[NormalizedPart],
        current_assistant_index: int | None,
    ) -> int | None:
        """Append reasoning to the active assistant group or create a new one."""
        if not parts:
            return current_assistant_index

        folded = try_append_to_assistant_group(
            messages,
            current_assistant_index=current_assistant_index,
            parts=parts,
            blocking_part_types=("text", "tool"),
        )
        if folded is not None:
            return folded

        messages.append(
            build_message(
                message_id=message_id,
                role="assistant",
                agent="codex",
                time_created=timestamp_ms,
                parts=list(parts),
            )
        )
        return len(messages) - 1

    def _append_assistant_text(
        self,
        messages: list[NormalizedMessage],
        *,
        message_id: str,
        timestamp_ms: int,
        parts: list[NormalizedPart],
        current_assistant_index: int | None,
    ) -> int | None:
        """Append text to the active assistant group or create a new one."""
        if not parts:
            return current_assistant_index

        folded = try_append_to_assistant_group(
            messages,
            current_assistant_index=current_assistant_index,
            parts=parts,
            blocking_part_types=("tool",),
        )
        if folded is not None:
            return folded

        assistant_index = self._append_assistant_text_message(
            messages,
            message_id=message_id,
            timestamp_ms=timestamp_ms,
            parts=parts,
        )
        return assistant_index if assistant_index is not None else current_assistant_index

    def _finalize_pending_plan(
        self,
        messages: list[NormalizedMessage],
        pending_plan_location: tuple[int, int] | None,
        *,
        approval_status: str = "fail",
        output: str | None = None,
    ) -> None:
        """Finalize the pending plan part in place."""
        if pending_plan_location is None:
            return

        message_index, part_index = pending_plan_location
        plan_part = messages[message_index]["parts"][part_index]
        if not is_plan_part(plan_part):
            return
        plan_part["approval_status"] = approval_status
        plan_part["output"] = output

    def _message_contains_plan_part(self, message: NormalizedMessage) -> bool:
        """Whether one message contains a plan part."""
        return message_has_part_type(message, "plan")

    def _extract_visible_user_text(self, parts: list[NormalizedPart]) -> str | None:
        """Extract visible text from user parts."""
        text_parts: list[str] = []
        for part in parts:
            if part.get("type") != "text":
                continue
            text = str(part.get("text", "")).strip()
            if text:
                text_parts.append(text)

        if not text_parts:
            return None

        return "\n\n".join(text_parts)

    @staticmethod
    def _is_injected_user_context(content: Any) -> bool:
        """Recognize complete Codex context blocks without discarding mixed user input."""
        if not isinstance(content, list) or not content:
            return False
        if any(
            not isinstance(item, dict) or item.get("type") != "input_text" or not isinstance(item.get("text"), str)
            for item in content
        ):
            return False
        user_text = "\n\n".join(item["text"] for item in content).lstrip("\r\n").rstrip()
        if not user_text:
            return False
        offset = 0
        while offset < len(user_text):
            match = _USER_CONTEXT_BLOCK.match(user_text, offset)
            if match is None:
                return False
            offset = match.end()
        return True

    def _attach_tool_part_to_latest_assistant(
        self,
        messages: list[NormalizedMessage],
        tool_part: NormalizedPart,
        timestamp_ms: int,
        latest_assistant_text_index: int | None,
    ) -> tuple[int, int]:
        """Attach one tool call to the latest assistant text message or create a fallback one."""
        if latest_assistant_text_index is not None:
            messages[latest_assistant_text_index]["parts"].append(tool_part)
            return latest_assistant_text_index, len(messages[latest_assistant_text_index]["parts"]) - 1

        messages.append(
            build_message(
                message_id=str(timestamp_ms),
                role="assistant",
                time_created=timestamp_ms,
                mode="tool",
                parts=[tool_part],
            )
        )
        return len(messages) - 1, 0

    def _attach_tool_call_to_latest_assistant(
        self,
        messages: list[NormalizedMessage],
        payload: dict[str, Any],
        timestamp_ms: int,
        latest_assistant_text_index: int | None,
    ) -> tuple[int, int]:
        """Attach one function_call tool part to the latest assistant text message."""
        tool_part = self._build_function_tool_part(payload, timestamp_ms)
        return self._attach_tool_part_to_latest_assistant(
            messages,
            tool_part,
            timestamp_ms,
            latest_assistant_text_index,
        )

    def _attach_custom_tool_call_to_latest_assistant(
        self,
        messages: list[NormalizedMessage],
        payload: dict[str, Any],
        timestamp_ms: int,
        latest_assistant_text_index: int | None,
    ) -> tuple[int, int]:
        """Attach one custom_tool_call tool part to the latest assistant text message."""
        tool_part = self._build_custom_tool_part(payload, timestamp_ms)
        return self._attach_tool_part_to_latest_assistant(
            messages,
            tool_part,
            timestamp_ms,
            latest_assistant_text_index,
        )

    def _backfill_tool_output(
        self,
        messages: list[NormalizedMessage],
        pending_tool_calls: dict[str, tuple[int, int]],
        *,
        call_id: str,
        output_parts: list[NormalizedPart],
        raw_output: Any,
        subagent_call_map: dict[str, dict[str, str]],
        subagent_nicknames: dict[str, str],
    ) -> bool:
        """Backfill tool output to its matching tool part."""
        tool_part = backfill_tool_state(
            messages,
            pending_tool_calls,
            call_id=call_id,
            output_parts=output_parts,
        )
        if tool_part is None:
            return False

        self._record_subagent_output(
            tool_part=tool_part,
            output_parts=output_parts,
            raw_output=raw_output,
            call_id=call_id,
            subagent_call_map=subagent_call_map,
            subagent_nicknames=subagent_nicknames,
        )
        return True

    def _convert_record_to_messages(
        self,
        *,
        data: dict[str, Any],
        state: _CodexAssemblyState,
    ) -> None:
        """Convert one Codex record into unified messages while preserving stream relationships."""
        msg_type = data.get("type", "")
        if msg_type != "response_item":
            return

        payload = data.get("payload")
        if not isinstance(payload, dict):
            return

        timestamp_ms = self._parse_timestamp_ms(data)
        message_id = str(data.get("timestamp", ""))
        item_type = payload.get("type", "")
        if item_type == "message":
            self._convert_message_response_item(
                state,
                payload=payload,
                message_id=message_id,
                timestamp_ms=timestamp_ms,
            )
        elif item_type == "reasoning":
            self._convert_reasoning_response_item(
                state,
                payload=payload,
                message_id=message_id,
                timestamp_ms=timestamp_ms,
            )
        elif item_type in {"function_call", "custom_tool_call"}:
            self._convert_tool_call_response_item(
                state,
                payload=payload,
                timestamp_ms=timestamp_ms,
                is_custom=item_type == "custom_tool_call",
            )
        elif item_type in {"function_call_output", "custom_tool_call_output"}:
            self._convert_tool_output_response_item(
                state,
                payload=payload,
                message_id=message_id,
                timestamp_ms=timestamp_ms,
                is_custom=item_type == "custom_tool_call_output",
            )

    def _convert_message_response_item(
        self,
        state: _CodexAssemblyState,
        *,
        payload: dict[str, Any],
        message_id: str,
        timestamp_ms: int,
    ) -> None:
        role = str(payload.get("role", "unknown"))
        parts = self._extract_message_content_parts(role, payload.get("content", []), timestamp_ms)
        if not parts:
            return
        if role == "user" and self._is_injected_user_context(payload.get("content")):
            role = "developer"

        if role == "assistant":
            self._append_assistant_message_item(
                state,
                message_id=message_id,
                timestamp_ms=timestamp_ms,
                parts=parts,
            )
            return

        user_text = self._extract_visible_user_text(parts) if role == "user" else None
        if state.pending_plan_location is not None and user_text is not None:
            approval_status = "success" if user_text.lstrip().startswith(PLAN_APPROVAL_PREFIX) else "fail"
            output = None if approval_status == "success" else user_text
            self._finalize_pending_plan(
                state.messages,
                state.pending_plan_location,
                approval_status=approval_status,
                output=output,
            )
            state.pending_plan_location = None
            state.clear_assistant_group()
            return

        subagent_message = self._maybe_build_subagent_notification_message(
            message_id=message_id,
            timestamp_ms=timestamp_ms,
            role=role,
            parts=parts,
            subagent_nicknames=state.subagent_nicknames,
        )
        state.messages.append(
            subagent_message
            if subagent_message is not None
            else build_message(
                message_id=message_id,
                role=normalize_message_role(role),
                time_created=timestamp_ms,
                parts=parts,
            )
        )
        state.clear_assistant_group()

    def _append_assistant_message_item(
        self,
        state: _CodexAssemblyState,
        *,
        message_id: str,
        timestamp_ms: int,
        parts: list[NormalizedPart],
    ) -> None:
        if state.pending_plan_location is not None:
            self._finalize_pending_plan(state.messages, state.pending_plan_location)
            state.pending_plan_location = None

        assistant_index = self._append_assistant_text(
            state.messages,
            message_id=message_id,
            timestamp_ms=timestamp_ms,
            parts=parts,
            current_assistant_index=state.current_assistant_index,
        )
        if assistant_index is not None:
            state.current_assistant_index = assistant_index
        state.latest_assistant_text_index = state.current_assistant_index
        if assistant_index is not None and self._message_contains_plan_part(state.messages[assistant_index]):
            state.pending_plan_location = (assistant_index, len(state.messages[assistant_index]["parts"]) - 1)
            state.latest_assistant_text_index = None

    def _convert_reasoning_response_item(
        self,
        state: _CodexAssemblyState,
        *,
        payload: dict[str, Any],
        message_id: str,
        timestamp_ms: int,
    ) -> None:
        assistant_index = self._append_assistant_reasoning(
            state.messages,
            message_id=message_id,
            timestamp_ms=timestamp_ms,
            parts=self._extract_reasoning_parts(payload, timestamp_ms),
            current_assistant_index=state.current_assistant_index,
        )
        if assistant_index is not None:
            state.current_assistant_index = assistant_index

    def _convert_tool_call_response_item(
        self,
        state: _CodexAssemblyState,
        *,
        payload: dict[str, Any],
        timestamp_ms: int,
        is_custom: bool,
    ) -> None:
        attach_tool_call = (
            self._attach_custom_tool_call_to_latest_assistant
            if is_custom
            else self._attach_tool_call_to_latest_assistant
        )
        message_index, part_index = attach_tool_call(
            state.messages,
            payload,
            timestamp_ms,
            state.latest_assistant_text_index,
        )
        call_id = str(payload.get("call_id", ""))
        if call_id:
            state.pending_tool_calls[call_id] = (message_index, part_index)
        if state.latest_assistant_text_index is None and message_index == len(state.messages) - 1:
            state.current_assistant_index = message_index

    def _convert_tool_output_response_item(
        self,
        state: _CodexAssemblyState,
        *,
        payload: dict[str, Any],
        message_id: str,
        timestamp_ms: int,
        is_custom: bool,
    ) -> None:
        call_id = str(payload.get("call_id", ""))
        raw_output = payload.get("output")
        output_parts = (
            self._normalize_custom_tool_output(raw_output, timestamp_ms)
            if is_custom
            else self._normalize_output_parts(raw_output, timestamp_ms)
        )
        if self._backfill_tool_output(
            state.messages,
            state.pending_tool_calls,
            call_id=call_id,
            output_parts=output_parts,
            raw_output=raw_output,
            subagent_call_map=state.subagent_call_map,
            subagent_nicknames=state.subagent_nicknames,
        ):
            return

        fallback = build_fallback_tool_message(
            message_id=message_id,
            output_parts=output_parts,
            time_created=timestamp_ms,
            tool_call_id=call_id,
        )
        if fallback is not None:
            state.messages.append(fallback)
