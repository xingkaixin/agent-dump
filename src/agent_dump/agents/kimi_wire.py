from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, cast

from agent_dump.agents.jsonl_scan import JsonlObjectScan, skipped_records_diagnostic
from agent_dump.agents.message_assembly import (
    backfill_tool_state,
    build_fallback_tool_message,
    build_message,
    build_text_part,
    build_tool_part,
)
from agent_dump.agents.message_types import NormalizedMessage, NormalizedPart, ToolPart
from agent_dump.coercion import safe_epoch_datetime
from agent_dump.diagnostics import RecoverableDiagnostic

KIMI_TOOL_TITLE_MAP = {
    "ReadFile": "read",
    "Glob": "glob",
    "StrReplaceFile": "edit",
    "Grep": "grep",
    "WriteFile": "write",
    "Shell": "bash",
}

KIMI_IGNORED_TOOLS = {"SetTodoList"}


@dataclass(frozen=True)
class KimiWireParseResult:
    messages: list[NormalizedMessage]
    diagnostic: RecoverableDiagnostic | None


def map_kimi_tool_title(tool_name: str) -> str:
    return KIMI_TOOL_TITLE_MAP.get(tool_name, tool_name)


def should_ignore_kimi_tool(tool_name: str) -> bool:
    return tool_name in KIMI_IGNORED_TOOLS


def normalize_kimi_tool_arguments(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def parse_kimi_wire(wire_path: Path) -> KimiWireParseResult:
    parser = _KimiWireParser()
    scan = JsonlObjectScan(wire_path)
    for seq, record in scan.iter_with_line_numbers():
        parser.consume(seq, record)
    messages = [message for message in parser.messages if message.get("parts")]
    return KimiWireParseResult(messages=messages, diagnostic=skipped_records_diagnostic(scan))


@dataclass
class _KimiWireParser:
    messages: list[NormalizedMessage] = field(default_factory=list)
    pending_tool_calls: dict[str, tuple[int, int]] = field(default_factory=dict)
    open_tool_argument_buffer: dict[str, str] = field(default_factory=dict)
    ignored_tool_call_ids: set[str] = field(default_factory=set)
    current_assistant_index: int | None = None
    open_tool_call_id: str | None = None

    def consume(self, seq: int, record: dict[str, Any]) -> None:
        message = record.get("message")
        if not isinstance(message, dict):
            return
        message_type = message.get("type")
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return
        timestamp_ms = _timestamp_ms(record.get("timestamp"))

        if message_type == "TurnBegin":
            self._consume_turn_begin(seq, payload, timestamp_ms)
        elif message_type == "ContentPart":
            self._consume_content_part(seq, payload, timestamp_ms)
        elif message_type == "ToolCall":
            self._consume_tool_call(seq, payload, timestamp_ms)
        elif message_type == "ToolCallPart":
            self._consume_tool_call_part(payload)
        elif message_type == "ToolResult":
            self._consume_tool_result(seq, payload)

    def _consume_turn_begin(self, seq: int, payload: dict[str, Any], timestamp_ms: int) -> None:
        user_input = payload.get("user_input")
        text = ""
        if isinstance(user_input, list) and user_input and isinstance(user_input[0], dict):
            text = str(user_input[0].get("text", ""))
        if text.strip():
            self.messages.append(
                build_message(
                    message_id=f"wire-{seq}",
                    role="user",
                    parts=[build_text_part(text, timestamp_ms)],
                    time_created=timestamp_ms,
                )
            )
        self.current_assistant_index = None
        self.open_tool_call_id = None

    def _consume_content_part(self, seq: int, payload: dict[str, Any], timestamp_ms: int) -> None:
        assistant_index = self._get_or_create_assistant(f"wire-{seq}")
        assistant = self.messages[assistant_index]
        part_type = payload.get("type")
        if part_type == "think":
            text = str(payload.get("think", ""))
            if text.strip():
                assistant["parts"].append(build_text_part(text, timestamp_ms, part_type="reasoning"))
        elif part_type == "text":
            text = str(payload.get("text", ""))
            if text.strip():
                assistant["parts"].append(build_text_part(text, timestamp_ms))

    def _consume_tool_call(self, seq: int, payload: dict[str, Any], timestamp_ms: int) -> None:
        function = payload.get("function")
        tool_name = str(function.get("name", "")).strip() if isinstance(function, dict) else ""
        call_id = str(payload.get("id", "")).strip()
        if tool_name and call_id and should_ignore_kimi_tool(tool_name):
            self.ignored_tool_call_ids.add(call_id)
            self.open_tool_call_id = call_id
            return

        assistant_index = self._get_or_create_assistant(f"wire-{seq}")
        tool_part, call_id, buffer = _build_tool_part(payload, timestamp_ms)
        if tool_part is None or call_id is None:
            return
        assistant = self.messages[assistant_index]
        part_index = len(assistant["parts"])
        assistant["parts"].append(tool_part)
        assistant["mode"] = "tool"
        self.pending_tool_calls[call_id] = (assistant_index, part_index)
        self.open_tool_call_id = call_id
        if buffer is not None:
            self.open_tool_argument_buffer[call_id] = buffer

    def _consume_tool_call_part(self, payload: dict[str, Any]) -> None:
        call_id = self.open_tool_call_id
        if not call_id or call_id in self.ignored_tool_call_ids or call_id not in self.pending_tool_calls:
            return
        buffer = self.open_tool_argument_buffer.get(call_id, "") + str(payload.get("arguments_part", ""))
        try:
            parsed_arguments = json.loads(buffer)
        except json.JSONDecodeError:
            self.open_tool_argument_buffer[call_id] = buffer
            return

        message_index, part_index = self.pending_tool_calls[call_id]
        part = self.messages[message_index]["parts"][part_index]
        if part["type"] != "tool":
            return
        cast(ToolPart, part)["state"]["arguments"] = parsed_arguments
        self.open_tool_argument_buffer.pop(call_id, None)

    def _consume_tool_result(self, seq: int, payload: dict[str, Any]) -> None:
        call_id = str(payload.get("tool_call_id", "")).strip()
        if call_id and call_id in self.ignored_tool_call_ids:
            return
        output_parts = _normalize_tool_output_parts(payload.get("return_value"))
        if (
            backfill_tool_state(
                self.messages,
                self.pending_tool_calls,
                call_id=call_id,
                output_parts=output_parts,
            )
            is not None
        ):
            return
        fallback_message = build_fallback_tool_message(
            message_id=f"wire-{seq}",
            output_parts=output_parts,
            tool_call_id=call_id or None,
        )
        if fallback_message:
            self.messages.append(fallback_message)

    def _get_or_create_assistant(self, message_id: str) -> int:
        if self.current_assistant_index is None:
            self.messages.append(
                build_message(
                    message_id=message_id,
                    role="assistant",
                    agent="kimi",
                    parts=[],
                )
            )
            self.current_assistant_index = len(self.messages) - 1
        return self.current_assistant_index


def _build_tool_part(
    payload: dict[str, Any], timestamp_ms: int
) -> tuple[NormalizedPart | None, str | None, str | None]:
    call_id = str(payload.get("id", "")).strip()
    function = payload.get("function")
    if not isinstance(function, dict) or not call_id:
        return None, None, None
    tool_name = str(function.get("name", "")).strip()
    if not tool_name:
        return None, None, None

    raw_arguments = function.get("arguments")
    normalized_arguments = normalize_kimi_tool_arguments(raw_arguments)
    buffer = raw_arguments if isinstance(raw_arguments, str) and isinstance(normalized_arguments, str) else None
    return (
        build_tool_part(
            tool_name=tool_name,
            call_id=call_id,
            title=map_kimi_tool_title(tool_name),
            state={"arguments": normalized_arguments, "output": None},
            timestamp_ms=timestamp_ms,
        ),
        call_id,
        buffer,
    )


def _normalize_tool_output_parts(return_value: Any) -> list[NormalizedPart]:
    if return_value is None:
        return []
    if isinstance(return_value, str):
        return [build_text_part(return_value)] if return_value.strip() else []
    if isinstance(return_value, (dict, list)):
        return [build_text_part(json.dumps(return_value, ensure_ascii=False, indent=2))]
    text = str(return_value)
    return [build_text_part(text)] if text.strip() else []


def _timestamp_ms(raw: Any) -> int:
    parsed = safe_epoch_datetime(raw, unit="s")
    return int(parsed.timestamp() * 1000) if parsed is not None else 0
