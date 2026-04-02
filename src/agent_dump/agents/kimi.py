"""
Kimi agent handler
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.paths import ProviderRoots, first_existing_path

KIMI_TOOL_TITLE_MAP = {
    "ReadFile": "read",
    "Glob": "glob",
    "StrReplaceFile": "edit",
    "Grep": "grep",
    "WriteFile": "write",
    "Shell": "bash",
}

KIMI_IGNORED_TOOLS = {"SetTodoList"}


class KimiAgent(BaseAgent):
    """Handler for Kimi sessions"""

    def __init__(self):
        super().__init__("kimi", "Kimi")
        self.base_path: Path | None = None

    def _find_base_path(self) -> Path | None:
        """Find the Kimi sessions directory"""
        roots = ProviderRoots.from_env_or_home()
        return first_existing_path(roots.kimi_root / "sessions", Path("data/kimi"))

    def _get_session_files(self, session_dir: Path) -> dict[str, Path | None]:
        """Get available session files for a Kimi session directory."""
        context_path = session_dir / "context.jsonl"
        wire_path = session_dir / "wire.jsonl"
        return {
            "context_file": context_path if context_path.exists() else None,
            "wire_file": wire_path if wire_path.exists() else None,
        }

    def _get_raw_source_path(self, session: Session) -> Path:
        """Pick the preferred raw source file for a Kimi session."""
        context_file = session.metadata.get("context_file")
        if context_file:
            return Path(context_file)

        wire_file = session.metadata.get("wire_file")
        if wire_file:
            return Path(wire_file)

        raise FileNotFoundError(f"No raw session file found for session: {session.id}")

    def is_available(self) -> bool:
        """Check if Kimi sessions exist"""
        self.base_path = self._find_base_path()
        if not self.base_path:
            return False
        return len(list(self.base_path.rglob("metadata.json"))) > 0

    def scan(self) -> list[Session]:
        """Scan for all available sessions"""
        if not self.is_available():
            return []
        return self.get_sessions(days=3650)

    def get_sessions(self, days: int = 7) -> list[Session]:
        """Get sessions from the last N days"""
        if not self.base_path:
            return []

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        sessions = []

        for metadata_file in self.base_path.rglob("metadata.json"):
            try:
                session = self._parse_session(metadata_file)
                if session and session.created_at >= cutoff_time:
                    sessions.append(session)
            except Exception as e:
                print(f"警告: 解析会话文件失败 {metadata_file}: {e}")
                continue

        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def _parse_session(self, metadata_path: Path) -> Session | None:
        """Parse a Kimi session from metadata file"""
        try:
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            session_dir = metadata_path.parent
            session_files = self._get_session_files(session_dir)
            context_path = session_files["context_file"]
            wire_path = session_files["wire_file"]

            if not context_path and not wire_path:
                return None

            session_id = metadata.get("session_id", "")
            title = metadata.get("title", "Untitled Session")
            wire_mtime = metadata.get("wire_mtime")
            created_at_ts = wire_mtime if isinstance(wire_mtime, (int, float)) else metadata_path.stat().st_mtime
            created_at = datetime.fromtimestamp(created_at_ts, tz=timezone.utc)

            return Session(
                id=session_id,
                title=title,
                created_at=created_at,
                updated_at=created_at,
                source_path=session_dir,
                metadata={
                    "context_file": str(context_path) if context_path else None,
                    "wire_file": str(wire_path) if wire_path else None,
                    "title_generated": metadata.get("title_generated", False),
                },
            )
        except Exception:
            return None

    def _build_session_data(self, session: Session, messages: list[dict], stats: dict[str, int | float]) -> dict:
        """Build unified session data payload."""
        return {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": str(session.source_path),
            "version": None,
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": messages,
        }

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        """Export the preferred raw Kimi session file."""
        source_path = self._get_raw_source_path(session)
        if not source_path.exists():
            raise FileNotFoundError(f"Raw session file not found: {source_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._build_raw_output_path(session, output_dir, suffix=".raw.jsonl")
        shutil.copy2(source_path, output_path)
        return output_path

    def _build_message(
        self,
        *,
        message_id: str,
        role: str,
        parts: list[dict],
        agent: str | None = None,
        mode: str | None = None,
        time_created: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        """Build one unified message."""
        message = {
            "id": message_id,
            "role": role,
            "agent": agent,
            "mode": mode,
            "model": None,
            "provider": None,
            "time_created": time_created,
            "time_completed": None,
            "tokens": {},
            "cost": 0,
            "parts": parts,
        }
        if extra:
            message.update(extra)
        return message

    def _build_text_part(self, text: str, time_created: int = 0) -> dict:
        """Build one text part."""
        return {
            "type": "text",
            "text": text,
            "time_created": time_created,
        }

    def _map_tool_title(self, tool_name: str) -> str:
        """Map Kimi tool names to unified short titles."""
        return KIMI_TOOL_TITLE_MAP.get(tool_name, tool_name)

    def _should_ignore_tool(self, tool_name: str) -> bool:
        """Check whether a tool should be excluded from export."""
        return tool_name in KIMI_IGNORED_TOOLS

    def _extract_kimi_total_tokens_from_raw(self, session_dir: Path) -> int | None:
        """Extract the final cumulative token count from raw Kimi jsonl."""
        raw_path = session_dir / "context.jsonl"
        if not raw_path.exists():
            raw_path = session_dir / "wire.jsonl"
        if not raw_path.exists():
            return None

        total_tokens: int | None = None
        with open(raw_path, encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if data.get("role") != "_usage":
                    continue

                token_count = data.get("token_count")
                if isinstance(token_count, (int, float)) and not isinstance(token_count, bool):
                    total_tokens = int(token_count)

        return total_tokens

    def _extract_kimi_stats_from_wire(self, session_dir: Path) -> dict[str, int | float]:
        """Extract best-effort usage stats from wire.jsonl."""
        stats: dict[str, int | float] = {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "message_count": 0,
        }

        wire_path = session_dir / "wire.jsonl"
        if wire_path.exists():
            with open(wire_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    token_usage = data.get("message", {}).get("usage", {})
                    if not isinstance(token_usage, dict):
                        continue

                    stats["total_input_tokens"] += int(token_usage.get("input_tokens", 0))
                    stats["total_output_tokens"] += int(token_usage.get("output_tokens", 0))

        total_tokens = self._extract_kimi_total_tokens_from_raw(session_dir)
        if total_tokens is not None:
            stats["total_tokens"] = total_tokens

        return stats

    def _convert_context_content_part(self, item: dict[str, Any]) -> dict | None:
        """Convert one assistant content part from context.jsonl."""
        part_type = item.get("type")
        if part_type == "think":
            text = str(item.get("think", ""))
            if not text.strip():
                return None
            return {
                "type": "reasoning",
                "text": text,
                "time_created": 0,
            }

        if part_type == "text":
            text = str(item.get("text", ""))
            if not text.strip():
                return None
            return {
                "type": "text",
                "text": text,
                "time_created": 0,
            }

        return None

    def _normalize_tool_arguments(self, raw: Any) -> Any:
        """Normalize tool call arguments."""
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
        return raw

    def _normalize_tool_output_parts(self, content: Any) -> list[dict]:
        """Normalize tool output content to text parts."""
        if isinstance(content, str):
            return [self._build_text_part(content)] if content.strip() else []

        if isinstance(content, list):
            parts: list[dict] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = str(item.get("text", ""))
                    if text.strip():
                        parts.append(self._build_text_part(text))
                elif isinstance(item, str) and item.strip():
                    parts.append(self._build_text_part(item))
            return parts

        if content is None:
            return []

        text = str(content)
        return [self._build_text_part(text)] if text.strip() else []

    def _normalize_wire_tool_output_parts(self, return_value: Any) -> list[dict]:
        """Normalize wire tool output content to text parts."""
        if return_value is None:
            return []
        if isinstance(return_value, str):
            return [self._build_text_part(return_value)] if return_value.strip() else []
        if isinstance(return_value, (dict, list)):
            return [self._build_text_part(json.dumps(return_value, ensure_ascii=False, indent=2))]
        text = str(return_value)
        return [self._build_text_part(text)] if text.strip() else []

    def _convert_context_tool_call(self, tool_call: dict[str, Any]) -> dict | None:
        """Convert one assistant tool call from context.jsonl."""
        if tool_call.get("type") != "function":
            return None

        function = tool_call.get("function", {})
        if not isinstance(function, dict):
            return None

        tool_name = str(function.get("name", "")).strip()
        call_id = str(tool_call.get("id", "")).strip()
        if not tool_name or not call_id:
            return None

        return {
            "type": "tool",
            "tool": tool_name,
            "callID": call_id,
            "title": self._map_tool_title(tool_name),
            "state": {
                "arguments": self._normalize_tool_arguments(function.get("arguments")),
                "output": None,
            },
            "time_created": 0,
        }

    def _convert_context_user_message(self, record: dict[str, Any], seq: int) -> dict | None:
        """Convert one user record from context.jsonl."""
        content = record.get("content", "")
        text = str(content)
        if not text.strip():
            return None

        return self._build_message(
            message_id=f"context-{seq}",
            role="user",
            parts=[self._build_text_part(text)],
        )

    def _build_context_assistant_message(
        self,
        record: dict[str, Any],
        seq: int,
        ignored_tool_call_ids: set[str],
    ) -> tuple[dict | None, dict[str, int]]:
        """Build one assistant message and record tool part indexes."""
        parts: list[dict] = []
        tool_indexes: dict[str, int] = {}

        content = record.get("content", [])
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                part = self._convert_context_content_part(item)
                if part:
                    parts.append(part)

        tool_calls = record.get("tool_calls", [])
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function", {})
                tool_name = str(function.get("name", "")).strip() if isinstance(function, dict) else ""
                call_id = str(tool_call.get("id", "")).strip()
                if tool_name and call_id and self._should_ignore_tool(tool_name):
                    ignored_tool_call_ids.add(call_id)
                    continue
                tool_part = self._convert_context_tool_call(tool_call)
                if tool_part:
                    tool_indexes[tool_part["callID"]] = len(parts)
                    parts.append(tool_part)

        if not parts:
            return None, {}

        message = self._build_message(
            message_id=f"context-{seq}",
            role="assistant",
            agent="kimi",
            mode="tool" if all(part.get("type") == "tool" for part in parts) else None,
            parts=parts,
        )
        return message, tool_indexes

    def _build_fallback_tool_message(
        self,
        *,
        message_id: str,
        tool_call_id: str | None,
        output_parts: list[dict],
    ) -> dict | None:
        """Build fallback tool message when tool output cannot be associated."""
        if not output_parts:
            return None

        extra = {"tool_call_id": tool_call_id} if tool_call_id else None
        return self._build_message(
            message_id=message_id,
            role="tool",
            parts=output_parts,
            extra=extra,
        )

    def _backfill_tool_output(
        self,
        output_parts: list[dict],
        tool_call_id: str,
        messages: list[dict],
        pending_tool_calls: dict[str, tuple[int, int]],
    ) -> bool:
        """Backfill tool output into the corresponding assistant tool part."""
        if not output_parts or not tool_call_id:
            return False

        location = pending_tool_calls.get(tool_call_id)
        if location is None:
            return False

        message_index, part_index = location
        state = messages[message_index]["parts"][part_index].setdefault("state", {})
        state["output"] = output_parts
        return True

    def _convert_context_record(
        self,
        record: dict[str, Any],
        seq: int,
        messages: list[dict],
        pending_tool_calls: dict[str, tuple[int, int]],
        ignored_tool_call_ids: set[str],
    ) -> None:
        """Convert one context record and update parsing state."""
        role = record.get("role")
        if role in {"_checkpoint", "_usage"}:
            return

        if role == "user":
            message = self._convert_context_user_message(record, seq)
            if message:
                messages.append(message)
            return

        if role == "assistant":
            message, tool_indexes = self._build_context_assistant_message(record, seq, ignored_tool_call_ids)
            if not message:
                return
            message_index = len(messages)
            messages.append(message)
            for tool_call_id, part_index in tool_indexes.items():
                pending_tool_calls[tool_call_id] = (message_index, part_index)
            return

        if role == "tool":
            tool_call_id = str(record.get("tool_call_id", "")).strip()
            if tool_call_id and tool_call_id in ignored_tool_call_ids:
                return
            output_parts = self._normalize_tool_output_parts(record.get("content"))
            if self._backfill_tool_output(output_parts, tool_call_id, messages, pending_tool_calls):
                return
            fallback_message = self._build_fallback_tool_message(
                message_id=f"context-{seq}",
                tool_call_id=tool_call_id or None,
                output_parts=output_parts,
            )
            if fallback_message:
                messages.append(fallback_message)

    def _get_session_data_from_context(self, session: Session) -> dict:
        """Build unified session data from context.jsonl."""
        context_path = session.source_path / "context.jsonl"
        if not context_path.exists():
            raise FileNotFoundError(f"Context file not found: {context_path}")

        messages: list[dict] = []
        pending_tool_calls: dict[str, tuple[int, int]] = {}
        ignored_tool_call_ids: set[str] = set()

        with open(context_path, encoding="utf-8") as f:
            for seq, line in enumerate(f, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"警告: 转换 context 记录失败: {e}")
                    continue
                self._convert_context_record(
                    record,
                    seq,
                    messages,
                    pending_tool_calls,
                    ignored_tool_call_ids,
                )

        stats = self._extract_kimi_stats_from_wire(session.source_path)
        stats["message_count"] = len(messages)
        return self._build_session_data(session, messages, stats)

    def _create_wire_assistant_message(self, message_id: str) -> dict:
        """Create one assistant message for wire state machine."""
        return self._build_message(
            message_id=message_id,
            role="assistant",
            agent="kimi",
            parts=[],
        )

    def _get_or_create_wire_assistant(
        self,
        messages: list[dict],
        current_assistant_index: int | None,
        message_id: str,
    ) -> int:
        """Get or create current assistant message index."""
        if current_assistant_index is not None:
            return current_assistant_index
        messages.append(self._create_wire_assistant_message(message_id))
        return len(messages) - 1

    def _append_wire_content_part(self, assistant_message: dict, payload: dict[str, Any], timestamp_ms: int) -> None:
        """Append one wire content part to assistant message."""
        part_type = payload.get("type")
        if part_type == "think":
            text = str(payload.get("think", ""))
            if text.strip():
                assistant_message["parts"].append(
                    {
                        "type": "reasoning",
                        "text": text,
                        "time_created": timestamp_ms,
                    }
                )
        elif part_type == "text":
            text = str(payload.get("text", ""))
            if text.strip():
                assistant_message["parts"].append(
                    {
                        "type": "text",
                        "text": text,
                        "time_created": timestamp_ms,
                    }
                )

    def _create_wire_tool_part(
        self, payload: dict[str, Any], timestamp_ms: int
    ) -> tuple[dict | None, str | None, str | None]:
        """Create one wire tool part and optional raw arguments buffer."""
        call_id = str(payload.get("id", "")).strip()
        function = payload.get("function", {})
        if not isinstance(function, dict) or not call_id:
            return None, None, None

        tool_name = str(function.get("name", "")).strip()
        if not tool_name:
            return None, None, None

        raw_arguments = function.get("arguments")
        normalized_arguments = self._normalize_tool_arguments(raw_arguments)
        buffer = raw_arguments if isinstance(raw_arguments, str) and isinstance(normalized_arguments, str) else None

        tool_part = {
            "type": "tool",
            "tool": tool_name,
            "callID": call_id,
            "title": self._map_tool_title(tool_name),
            "state": {
                "arguments": normalized_arguments,
                "output": None,
            },
            "time_created": timestamp_ms,
        }
        return tool_part, call_id, buffer

    def _append_wire_tool_call_part(
        self,
        arguments_part: str,
        open_tool_call_id: str | None,
        open_tool_argument_buffer: dict[str, str],
        messages: list[dict],
        pending_tool_calls: dict[str, tuple[int, int]],
    ) -> None:
        """Append ToolCallPart fragments to the active tool call."""
        if not open_tool_call_id or open_tool_call_id not in pending_tool_calls:
            return

        buffer = open_tool_argument_buffer.get(open_tool_call_id, "")
        buffer += arguments_part
        try:
            parsed_arguments = json.loads(buffer)
        except json.JSONDecodeError:
            open_tool_argument_buffer[open_tool_call_id] = buffer
            return

        message_index, part_index = pending_tool_calls[open_tool_call_id]
        messages[message_index]["parts"][part_index]["state"]["arguments"] = parsed_arguments
        open_tool_argument_buffer.pop(open_tool_call_id, None)

    def _get_session_data_from_wire(self, session: Session) -> dict:
        """Build unified session data from legacy wire.jsonl."""
        wire_path = session.source_path / "wire.jsonl"
        if not wire_path.exists():
            raise FileNotFoundError(f"Wire file not found: {wire_path}")

        messages: list[dict] = []
        pending_tool_calls: dict[str, tuple[int, int]] = {}
        open_tool_argument_buffer: dict[str, str] = {}
        ignored_tool_call_ids: set[str] = set()
        current_assistant_index: int | None = None
        open_tool_call_id: str | None = None

        with open(wire_path, encoding="utf-8") as f:
            for seq, line in enumerate(f, start=1):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"警告: 转换 wire 记录失败: {e}")
                    continue

                message = data.get("message", {})
                msg_type = message.get("type", "")
                payload = message.get("payload", {})
                timestamp = data.get("timestamp", 0)
                timestamp_ms = int(timestamp * 1000) if isinstance(timestamp, (int, float)) else 0

                if msg_type == "TurnBegin":
                    user_input = payload.get("user_input", [])
                    text = ""
                    if user_input and isinstance(user_input, list):
                        text = str(user_input[0].get("text", ""))
                    if text.strip():
                        messages.append(
                            self._build_message(
                                message_id=f"wire-{seq}",
                                role="user",
                                parts=[self._build_text_part(text, timestamp_ms)],
                                time_created=timestamp_ms,
                            )
                        )
                    current_assistant_index = None
                    open_tool_call_id = None
                    continue

                if msg_type == "ContentPart":
                    current_assistant_index = self._get_or_create_wire_assistant(
                        messages, current_assistant_index, f"wire-{seq}"
                    )
                    self._append_wire_content_part(messages[current_assistant_index], payload, timestamp_ms)
                    continue

                if msg_type == "ToolCall":
                    function = payload.get("function", {})
                    tool_name = str(function.get("name", "")).strip() if isinstance(function, dict) else ""
                    call_id = str(payload.get("id", "")).strip()
                    if tool_name and call_id and self._should_ignore_tool(tool_name):
                        ignored_tool_call_ids.add(call_id)
                        open_tool_call_id = call_id
                        continue
                    current_assistant_index = self._get_or_create_wire_assistant(
                        messages, current_assistant_index, f"wire-{seq}"
                    )
                    tool_part, call_id, buffer = self._create_wire_tool_part(payload, timestamp_ms)
                    if tool_part is None or call_id is None:
                        continue
                    part_index = len(messages[current_assistant_index]["parts"])
                    messages[current_assistant_index]["parts"].append(tool_part)
                    messages[current_assistant_index]["mode"] = "tool"
                    pending_tool_calls[call_id] = (current_assistant_index, part_index)
                    open_tool_call_id = call_id
                    if buffer is not None:
                        open_tool_argument_buffer[call_id] = buffer
                    continue

                if msg_type == "ToolCallPart":
                    if open_tool_call_id and open_tool_call_id in ignored_tool_call_ids:
                        continue
                    arguments_part = str(payload.get("arguments_part", ""))
                    self._append_wire_tool_call_part(
                        arguments_part,
                        open_tool_call_id,
                        open_tool_argument_buffer,
                        messages,
                        pending_tool_calls,
                    )
                    continue

                if msg_type == "ToolResult":
                    tool_call_id = str(payload.get("tool_call_id", "")).strip()
                    if tool_call_id and tool_call_id in ignored_tool_call_ids:
                        continue
                    output_parts = self._normalize_wire_tool_output_parts(payload.get("return_value"))
                    if self._backfill_tool_output(output_parts, tool_call_id, messages, pending_tool_calls):
                        continue
                    fallback_message = self._build_fallback_tool_message(
                        message_id=f"wire-{seq}",
                        tool_call_id=tool_call_id or None,
                        output_parts=output_parts,
                    )
                    if fallback_message:
                        messages.append(fallback_message)
                    continue

                if msg_type in {
                    "StepBegin",
                    "StatusUpdate",
                    "ApprovalRequest",
                    "ApprovalResponse",
                    "TurnEnd",
                }:
                    continue

        messages = [message for message in messages if message.get("parts")]
        stats = self._extract_kimi_stats_from_wire(session.source_path)
        stats["message_count"] = len(messages)
        return self._build_session_data(session, messages, stats)

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary"""
        context_path = session.source_path / "context.jsonl"
        if context_path.exists():
            return self._get_session_data_from_context(session)
        return self._get_session_data_from_wire(session)

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format"""
        session_data = self.get_session_data(session)

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return output_path
