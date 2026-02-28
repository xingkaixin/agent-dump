"""
Codex agent handler
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.message_filter import filter_messages_for_export

CODEX_TOOL_TITLE_MAP = {
    "exec_command": "bash",
}


class CodexAgent(BaseAgent):
    """Handler for Codex sessions"""

    def __init__(self):
        super().__init__("codex", "Codex")
        self.base_path: Path | None = None
        self._titles_cache: dict[str, str] | None = None

    def _find_base_path(self) -> Path | None:
        """Find the Codex sessions directory"""
        # Priority: user data directory > local development data
        paths = [
            Path.home() / ".codex/sessions",
            Path("data/codex"),
        ]

        for path in paths:
            if path.exists():
                return path
        return None

    def _load_titles_cache(self) -> dict[str, str]:
        """Load session titles from global state file"""
        if self._titles_cache is not None:
            return self._titles_cache

        titles: dict[str, str] = {}
        global_state_path = Path.home() / ".codex/.codex-global-state.json"

        if global_state_path.exists():
            try:
                with open(global_state_path, encoding="utf-8") as f:
                    data = json.load(f)
                titles = data.get("thread-titles", {}).get("titles", {})
            except Exception as e:
                print(f"警告: 加载标题缓存失败: {e}")

        self._titles_cache = titles
        return titles

    def _get_session_title(self, session_id: str) -> str | None:
        """Get session title from global state by session ID"""
        titles = self._load_titles_cache()
        return titles.get(session_id)

    def is_available(self) -> bool:
        """Check if Codex sessions exist"""
        self.base_path = self._find_base_path()
        if not self.base_path:
            return False
        # Check if there are any jsonl files
        return len(list(self.base_path.rglob("*.jsonl"))) > 0

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

        for jsonl_file in self.base_path.rglob("*.jsonl"):
            try:
                session = self._parse_session_file(jsonl_file)
                if session and session.created_at >= cutoff_time:
                    sessions.append(session)
            except Exception as e:
                print(f"警告: 解析会话文件失败 {jsonl_file}: {e}")
                continue

        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def _extract_session_id_from_filename(self, file_path: Path) -> str:
        """Extract session ID from Codex filename

        Filename format: rollout-{timestamp}-{sessionId}.jsonl
        Example: rollout-2026-02-03T10-04-47-019c213e-c251-73a3-af66-0ec9d7cb9e29.jsonl
        """
        stem = file_path.stem  # rollout-2026-02-03T10-04-47-019c213e-c251-73a3-af66-0ec9d7cb9e29
        parts = stem.split("-")

        # Session ID is the last 5 parts (UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
        if len(parts) >= 5:
            # Last 5 parts form the UUID
            session_id = "-".join(parts[-5:])
            return session_id

        return stem

    def _parse_session_file(self, file_path: Path) -> Session | None:
        """Parse a single Codex session file"""
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            if not lines:
                return None

            # Parse first line to get session metadata
            first_line = json.loads(lines[0])
            payload = first_line.get("payload", {})

            session_id = payload.get("id", "")
            timestamp_str = payload.get("timestamp", "")

            if not session_id:
                # Extract from filename
                session_id = self._extract_session_id_from_filename(file_path)

            # Parse timestamp
            try:
                created_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception:
                # Try to get from file modification time
                stat = file_path.stat()
                created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            # Try to get title from global state first, then fall back to extracting from messages
            title = self._get_session_title(session_id)
            if not title:
                title = self._extract_title(lines)

            return Session(
                id=session_id,
                title=title,
                created_at=created_at,
                updated_at=created_at,
                source_path=file_path,
                metadata={
                    "cwd": payload.get("cwd", ""),
                    "cli_version": payload.get("cli_version", ""),
                    "model_provider": payload.get("model_provider", ""),
                },
            )
        except Exception:
            return None

    def _extract_title(self, lines: list[str]) -> str:
        """Extract title from session messages"""
        try:
            for line in lines[:10]:  # Check first 10 lines
                data = json.loads(line)
                payload = data.get("payload", {})

                # Look for user message
                if payload.get("type") == "message" and payload.get("role") == "user":
                    content = payload.get("content", [])
                    if content and isinstance(content, list):
                        text = content[0].get("text", "")
                        # Clean up the text
                        text = text.strip().replace("\n", " ")[:100]
                        return text
        except Exception as e:
            print(f"警告: 提取标题失败: {e}")

        return "Untitled Session"

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary"""
        if not session.source_path.exists():
            raise FileNotFoundError(f"Session file not found: {session.source_path}")

        messages: list[dict[str, Any]] = []
        pending_tool_calls: dict[str, tuple[int, int]] = {}
        current_assistant_index: int | None = None
        latest_assistant_text_index: int | None = None
        stats = {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "message_count": 0,
        }

        with open(session.source_path, encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    current_assistant_index, latest_assistant_text_index = self._convert_record_to_messages(
                        data=data,
                        messages=messages,
                        pending_tool_calls=pending_tool_calls,
                        current_assistant_index=current_assistant_index,
                        latest_assistant_text_index=latest_assistant_text_index,
                    )
                    # Preserve the existing best-effort token extraction behavior.
                    if "token_count" in str(data):
                        info = data.get("payload", {}).get("info", {})
                        if info:
                            token_usage = info.get("total_token_usage", {})
                            stats["total_input_tokens"] += token_usage.get("input_tokens", 0)
                            stats["total_output_tokens"] += token_usage.get("output_tokens", 0)
                except Exception as e:
                    print(f"警告: 转换消息格式失败: {e}")
                    continue

        stats["message_count"] = len(messages)

        return {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": session.metadata.get("cwd", ""),
            "version": session.metadata.get("cli_version", ""),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": messages,
        }

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format"""
        session_data = self.get_session_data(session)
        messages = session_data.get("messages")
        if isinstance(messages, list):
            session_data["messages"] = filter_messages_for_export(messages)

        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return output_path

    def _parse_timestamp_ms(self, data: dict[str, Any]) -> int:
        """Parse record timestamp into milliseconds."""
        timestamp_str = str(data.get("timestamp", "")).strip()
        if not timestamp_str:
            return 0

        try:
            parsed = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            return 0

        return int(parsed.timestamp() * 1000)

    def _map_tool_title(self, tool_name: str) -> str:
        """Map Codex tool names to unified short titles."""
        return CODEX_TOOL_TITLE_MAP.get(tool_name, tool_name)

    def _build_message(
        self,
        *,
        message_id: str,
        role: str,
        time_created: int,
        parts: list[dict[str, Any]],
        agent: str | None = None,
        mode: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    def _build_text_part(self, text: str, timestamp_ms: int, part_type: str = "text") -> dict[str, Any]:
        """Build one text-like part."""
        return {
            "type": part_type,
            "text": text,
            "time_created": timestamp_ms,
        }

    def _build_tool_part(self, payload: dict[str, Any], timestamp_ms: int) -> dict[str, Any]:
        """Build one tool part from a function_call payload."""
        tool_name = str(payload.get("name", ""))
        return {
            "type": "tool",
            "tool": tool_name,
            "callID": str(payload.get("call_id", "")),
            "title": self._map_tool_title(tool_name),
            "state": {"arguments": payload.get("arguments", {})},
            "time_created": timestamp_ms,
        }

    def _normalize_output_parts(self, output: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        """Normalize tool output into text parts."""
        if output is None:
            return []
        if isinstance(output, str):
            return [self._build_text_part(output, timestamp_ms)]
        return [self._build_text_part(str(output), timestamp_ms)]

    def _extract_message_content_parts(
        self, role: str, content: Any, timestamp_ms: int
    ) -> list[dict[str, Any]]:
        """Extract text parts from a response_item message payload."""
        if not isinstance(content, list):
            return []

        parts: list[dict[str, Any]] = []
        is_assistant = role == "assistant"
        supported_types = {"output_text"} if is_assistant else {"input_text"}

        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type not in supported_types:
                continue
            parts.append(self._build_text_part(str(item.get("text", "")), timestamp_ms))

        return parts

    def _extract_reasoning_parts(self, payload: dict[str, Any], timestamp_ms: int) -> list[dict[str, Any]]:
        """Extract reasoning summary text parts."""
        summary = payload.get("summary", [])
        if not isinstance(summary, list):
            return []

        parts: list[dict[str, Any]] = []
        for item in summary:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "summary_text":
                continue
            parts.append(self._build_text_part(str(item.get("text", "")), timestamp_ms, part_type="reasoning"))
        return parts

    def _append_assistant_text_message(
        self,
        messages: list[dict[str, Any]],
        *,
        message_id: str,
        timestamp_ms: int,
        parts: list[dict[str, Any]],
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
            self._build_message(
                message_id=message_id,
                role="assistant",
                agent="codex",
                time_created=timestamp_ms,
                parts=parts,
            )
        )
        return len(messages) - 1

    def _message_has_part_type(self, message: dict[str, Any], part_type: str) -> bool:
        """Whether a message already contains a given part type."""
        return any(part.get("type") == part_type for part in message.get("parts", []))

    def _append_part_if_new(self, message: dict[str, Any], part: dict[str, Any]) -> None:
        """Append a part unless it duplicates the current tail part."""
        parts = message.get("parts", [])
        if parts and parts[-1] == part:
            return
        parts.append(part)

    def _append_assistant_reasoning(
        self,
        messages: list[dict[str, Any]],
        *,
        message_id: str,
        timestamp_ms: int,
        parts: list[dict[str, Any]],
        current_assistant_index: int | None,
    ) -> int | None:
        """Append reasoning to the active assistant group or create a new one."""
        if not parts:
            return current_assistant_index

        if current_assistant_index is not None:
            message = messages[current_assistant_index]
            has_text = self._message_has_part_type(message, "text")
            has_tool = self._message_has_part_type(message, "tool")
            if not has_text and not has_tool:
                for part in parts:
                    self._append_part_if_new(message, part)
                return current_assistant_index

        messages.append(
            self._build_message(
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
        messages: list[dict[str, Any]],
        *,
        message_id: str,
        timestamp_ms: int,
        parts: list[dict[str, Any]],
        current_assistant_index: int | None,
    ) -> int | None:
        """Append text to the active assistant group or create a new one."""
        if not parts:
            return current_assistant_index

        if current_assistant_index is not None:
            message = messages[current_assistant_index]
            has_tool = self._message_has_part_type(message, "tool")
            if not has_tool:
                for part in parts:
                    self._append_part_if_new(message, part)
                return current_assistant_index

        assistant_index = self._append_assistant_text_message(
            messages,
            message_id=message_id,
            timestamp_ms=timestamp_ms,
            parts=parts,
        )
        return assistant_index if assistant_index is not None else current_assistant_index

    def _attach_tool_call_to_latest_assistant(
        self,
        messages: list[dict[str, Any]],
        payload: dict[str, Any],
        timestamp_ms: int,
        latest_assistant_text_index: int | None,
    ) -> tuple[int, int]:
        """Attach one tool call to the latest assistant text message or create a fallback one."""
        tool_part = self._build_tool_part(payload, timestamp_ms)

        if latest_assistant_text_index is not None:
            messages[latest_assistant_text_index]["parts"].append(tool_part)
            return latest_assistant_text_index, len(messages[latest_assistant_text_index]["parts"]) - 1

        messages.append(
            self._build_message(
                message_id=str(timestamp_ms),
                role="assistant",
                time_created=timestamp_ms,
                mode="tool",
                parts=[tool_part],
            )
        )
        return len(messages) - 1, 0

    def _backfill_tool_output(
        self,
        messages: list[dict[str, Any]],
        pending_tool_calls: dict[str, tuple[int, int]],
        *,
        call_id: str,
        output_parts: list[dict[str, Any]],
    ) -> bool:
        """Backfill tool output to its matching tool part."""
        if not call_id or not output_parts:
            return False

        location = pending_tool_calls.get(call_id)
        if location is None:
            return False

        message_index, part_index = location
        state = messages[message_index]["parts"][part_index].setdefault("state", {})
        existing_output = state.get("output")
        if isinstance(existing_output, list):
            existing_output.extend(output_parts)
        elif existing_output is None:
            state["output"] = list(output_parts)
        else:
            state["output"] = [existing_output, *output_parts]
        return True

    def _build_fallback_tool_message(
        self,
        *,
        message_id: str,
        timestamp_ms: int,
        call_id: str,
        output_parts: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Build a fallback tool message when output cannot be associated."""
        if not output_parts:
            return None

        extra = {"tool_call_id": call_id} if call_id else None
        return self._build_message(
            message_id=message_id,
            role="tool",
            time_created=timestamp_ms,
            parts=output_parts,
            extra=extra,
        )

    def _convert_record_to_messages(
        self,
        *,
        data: dict[str, Any],
        messages: list[dict[str, Any]],
        pending_tool_calls: dict[str, tuple[int, int]],
        current_assistant_index: int | None,
        latest_assistant_text_index: int | None,
    ) -> tuple[int | None, int | None]:
        """Convert one Codex record into unified messages while preserving stream relationships."""
        msg_type = data.get("type", "")
        payload = data.get("payload", {})
        timestamp_ms = self._parse_timestamp_ms(data)
        message_id = str(data.get("timestamp", ""))

        if msg_type == "session_meta":
            return current_assistant_index, latest_assistant_text_index

        if msg_type == "response_item":
            item_type = payload.get("type", "")

            if item_type == "message":
                role = str(payload.get("role", "unknown"))
                parts = self._extract_message_content_parts(role, payload.get("content", []), timestamp_ms)
                if not parts:
                    return current_assistant_index, latest_assistant_text_index

                if role == "assistant":
                    assistant_index = self._append_assistant_text(
                        messages,
                        message_id=message_id,
                        timestamp_ms=timestamp_ms,
                        parts=parts,
                        current_assistant_index=current_assistant_index,
                    )
                    next_index = (
                        assistant_index if assistant_index is not None else current_assistant_index
                    )
                    return next_index, next_index

                messages.append(
                    self._build_message(
                        message_id=message_id,
                        role=role,
                        time_created=timestamp_ms,
                        parts=parts,
                    )
                )
                return None, None

            if item_type == "reasoning":
                parts = self._extract_reasoning_parts(payload, timestamp_ms)
                assistant_index = self._append_assistant_reasoning(
                    messages,
                    message_id=message_id,
                    timestamp_ms=timestamp_ms,
                    parts=parts,
                    current_assistant_index=current_assistant_index,
                )
                next_index = assistant_index if assistant_index is not None else current_assistant_index
                return next_index, latest_assistant_text_index

            if item_type == "function_call":
                message_index, part_index = self._attach_tool_call_to_latest_assistant(
                    messages,
                    payload,
                    timestamp_ms,
                    latest_assistant_text_index,
                )
                call_id = str(payload.get("call_id", ""))
                if call_id:
                    pending_tool_calls[call_id] = (message_index, part_index)
                next_current_index = current_assistant_index
                if latest_assistant_text_index is None and message_index == len(messages) - 1:
                    next_current_index = message_index
                return next_current_index, latest_assistant_text_index

            if item_type == "function_call_output":
                call_id = str(payload.get("call_id", ""))
                output_parts = self._normalize_output_parts(payload.get("output"), timestamp_ms)
                if self._backfill_tool_output(
                    messages,
                    pending_tool_calls,
                    call_id=call_id,
                    output_parts=output_parts,
                ):
                    return current_assistant_index, latest_assistant_text_index

                fallback = self._build_fallback_tool_message(
                    message_id=message_id,
                    timestamp_ms=timestamp_ms,
                    call_id=call_id,
                    output_parts=output_parts,
                )
                if fallback:
                    messages.append(fallback)
                return current_assistant_index, latest_assistant_text_index

            return current_assistant_index, latest_assistant_text_index

        if msg_type == "event_msg":
            event_type = payload.get("type", "")
            if event_type == "agent_message":
                parts = [self._build_text_part(str(payload.get("message", "")), timestamp_ms)]
            elif event_type == "agent_reasoning":
                text = str(payload.get("text", payload.get("message", "")))
                parts = [self._build_text_part(text, timestamp_ms, part_type="reasoning")]
                assistant_index = self._append_assistant_reasoning(
                    messages,
                    message_id=message_id,
                    timestamp_ms=timestamp_ms,
                    parts=parts,
                    current_assistant_index=current_assistant_index,
                )
                next_index = assistant_index if assistant_index is not None else current_assistant_index
                return next_index, latest_assistant_text_index
            else:
                return current_assistant_index, latest_assistant_text_index

            assistant_index = self._append_assistant_text(
                messages,
                message_id=message_id,
                timestamp_ms=timestamp_ms,
                parts=parts,
                current_assistant_index=current_assistant_index,
            )
            next_index = assistant_index if assistant_index is not None else current_assistant_index
            return next_index, next_index

        return current_assistant_index, latest_assistant_text_index
