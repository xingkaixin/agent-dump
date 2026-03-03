"""
Claude Code agent handler
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.paths import ProviderRoots, first_existing_path


class ClaudeCodeAgent(BaseAgent):
    """Handler for Claude Code sessions"""

    def __init__(self):
        super().__init__("claudecode", "Claude Code")
        self.base_path: Path | None = None
        self._sessions_index_cache: dict[str, dict] = {}

    def _find_base_path(self) -> Path | None:
        """Find the Claude Code projects directory"""
        roots = ProviderRoots.from_env_or_home()
        return first_existing_path(roots.claude_root / "projects", Path("data/claudecode"))

    def _load_sessions_index(self, project_dir: Path) -> dict[str, dict]:
        """Load sessions index for a project"""
        index_path = project_dir / "sessions-index.json"
        if not index_path.exists():
            return {}

        try:
            with open(index_path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", [])
            # Build a map of sessionId to entry data
            return {entry["sessionId"]: entry for entry in entries}
        except Exception:
            return {}

    def _get_session_metadata(self, session_id: str, project_dir: Path) -> dict | None:
        """Get session metadata from sessions-index.json"""
        cache_key = f"{project_dir.name}:{session_id}"
        if cache_key not in self._sessions_index_cache:
            # Load index for this project
            project_index = self._load_sessions_index(project_dir)
            # Update cache with all entries from this project
            for sid, entry in project_index.items():
                self._sessions_index_cache[f"{project_dir.name}:{sid}"] = entry

        return self._sessions_index_cache.get(cache_key)

    def is_available(self) -> bool:
        """Check if Claude Code sessions exist"""
        self.base_path = self._find_base_path()
        if not self.base_path:
            return False
        # Check for jsonl files in project directories
        for project_dir in self.base_path.iterdir():
            if project_dir.is_dir():
                jsonl_files = list(project_dir.glob("*.jsonl"))
                if jsonl_files:
                    return True
        return False

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

        # Iterate through project directories
        for project_dir in self.base_path.iterdir():
            if not project_dir.is_dir():
                continue

            # Find all jsonl files (excluding index files)
            for jsonl_file in project_dir.glob("*.jsonl"):
                if jsonl_file.name == "sessions-index.json":
                    continue

                try:
                    session = self._parse_session_file(jsonl_file, project_dir)
                    if session and session.created_at >= cutoff_time:
                        sessions.append(session)
                except Exception as e:
                    print(f"警告: 解析会话文件失败 {jsonl_file}: {e}")
                    continue

        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def _parse_session_file(self, file_path: Path, project_dir: Path) -> Session | None:
        """Parse a single Claude Code session file"""
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            if not lines:
                return None

            # Extract session ID from filename
            session_id = file_path.stem

            # Parse first message to get timestamp
            first_line = json.loads(lines[0])
            timestamp_str = first_line.get("timestamp", "")

            try:
                created_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception:
                # Use file modification time
                stat = file_path.stat()
                created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            # Try to get title from sessions-index.json first
            metadata = self._get_session_metadata(session_id, project_dir)
            title = metadata["summary"] if metadata and metadata.get("summary") else self._extract_title(lines)

            return Session(
                id=session_id,
                title=title,
                created_at=created_at,
                updated_at=created_at,
                source_path=file_path,
                metadata={
                    "project": project_dir.name,
                    "cwd": first_line.get("cwd", ""),
                    "version": first_line.get("version", ""),
                },
            )
        except Exception:
            return None

    def get_session_uri(self, session: Session) -> str:
        """Get the agent session URI for a session - Claude uses 'claude://' scheme"""
        return f"claude://{session.id}"

    def _extract_title(self, lines: list[str]) -> str:
        """Extract title from user messages"""
        try:
            for line in lines[:20]:  # Check first 20 lines
                data = json.loads(line)
                msg = data.get("message", {})

                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if content:
                        # Handle both string and list content
                        if isinstance(content, list):
                            # Extract text from content list
                            texts = []
                            for item in content:
                                if isinstance(item, dict):
                                    texts.append(item.get("text", ""))
                                elif isinstance(item, str):
                                    texts.append(item)
                            content = " ".join(texts)
                        # Clean up and truncate
                        content = content.strip().replace("\n", " ")[:100]
                        return content
        except Exception as e:
            print(f"警告: 提取标题失败: {e}")

        return "Untitled Session"

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary"""
        if not session.source_path.exists():
            raise FileNotFoundError(f"Session file not found: {session.source_path}")

        messages: list[dict[str, Any]] = []
        pending_tool_calls: dict[str, tuple[int, int]] = {}
        ignored_tool_call_ids: set[str] = set()
        assistant_uuid_to_tool_calls: dict[str, list[str]] = {}
        assistant_state: dict[str, int | None] = {
            "current_index": None,
            "latest_text_index": None,
        }
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
                    self._convert_claude_record(
                        data,
                        messages,
                        pending_tool_calls,
                        ignored_tool_call_ids,
                        assistant_uuid_to_tool_calls,
                        assistant_state,
                    )
                except Exception as e:
                    print(f"警告: 转换消息格式失败: {e}")
                    continue

        stats["message_count"] = len(messages)

        return {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": session.metadata.get("cwd", ""),
            "version": session.metadata.get("version", ""),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": messages,
        }

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format"""
        session_data = self.get_session_data(session)

        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return output_path

    def _parse_timestamp_ms(self, data: dict[str, Any]) -> int:
        """Parse one Claude record timestamp into milliseconds."""
        timestamp_str = str(data.get("timestamp", "")).strip()
        if not timestamp_str:
            return 0
        try:
            return int(datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return 0

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

    def _build_text_part(self, text: str, timestamp_ms: int) -> dict[str, Any]:
        """Build one text part."""
        return {
            "type": "text",
            "text": text,
            "time_created": timestamp_ms,
        }

    def _build_reasoning_part(self, text: str, timestamp_ms: int) -> dict[str, Any]:
        """Build one reasoning part."""
        return {
            "type": "reasoning",
            "text": text,
            "time_created": timestamp_ms,
        }

    def _build_tool_part(self, part: dict[str, Any], timestamp_ms: int) -> dict[str, Any]:
        """Build one tool part from Claude tool_use content."""
        tool_name = str(part.get("name", ""))
        return {
            "type": "tool",
            "tool": tool_name,
            "callID": str(part.get("id", "")),
            "title": f"Tool: {tool_name}",
            "state": {
                "input": part.get("input", {}),
                "output": None,
            },
            "time_created": timestamp_ms,
        }

    def _normalize_claude_tool_output(self, content: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        """Normalize Claude tool output into text parts."""
        if isinstance(content, str):
            return [self._build_text_part(content, timestamp_ms)] if content.strip() else []

        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text", item.get("content", "")))
                    if text.strip():
                        parts.append(self._build_text_part(text, timestamp_ms))
                elif isinstance(item, str) and item.strip():
                    parts.append(self._build_text_part(item, timestamp_ms))
            return parts

        if content is None:
            return []

        text = str(content)
        return [self._build_text_part(text, timestamp_ms)] if text.strip() else []

    def _normalize_user_text_parts(self, content: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        """Normalize user-visible text content into text parts."""
        if isinstance(content, str):
            return [self._build_text_part(content, timestamp_ms)] if content.strip() else []

        if not isinstance(content, list):
            return []

        parts: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "tool_result":
                    continue
                text = str(item.get("text", ""))
                if text.strip():
                    parts.append(self._build_text_part(text, timestamp_ms))
            elif isinstance(item, str) and item.strip():
                parts.append(self._build_text_part(item, timestamp_ms))
        return parts

    def _message_has_part_type(self, message: dict[str, Any], part_type: str) -> bool:
        """Whether a message already contains the given part type."""
        return any(part.get("type") == part_type for part in message.get("parts", []))

    def _append_part_if_new(self, message: dict[str, Any], part: dict[str, Any]) -> None:
        """Append a part unless it duplicates the current tail part."""
        parts = message.get("parts", [])
        if parts and parts[-1] == part:
            return
        parts.append(part)

    def _apply_assistant_metadata(self, message: dict[str, Any], msg: dict[str, Any]) -> None:
        """Apply model/usage metadata to an assistant message when available."""
        model = msg.get("model")
        usage = msg.get("usage")
        if model and not message.get("model"):
            message["model"] = model
        if isinstance(usage, dict) and not message.get("tokens"):
            message["tokens"] = usage

    def _append_assistant_reasoning(
        self,
        messages: list[dict[str, Any]],
        *,
        message_id: str,
        msg: dict[str, Any],
        timestamp_ms: int,
        part: dict[str, Any],
        current_assistant_index: int | None,
    ) -> int:
        """Append reasoning to the active assistant group or create a new one."""
        if current_assistant_index is not None:
            message = messages[current_assistant_index]
            has_text = self._message_has_part_type(message, "text")
            has_tool = self._message_has_part_type(message, "tool")
            if not has_text and not has_tool:
                self._append_part_if_new(message, part)
                self._apply_assistant_metadata(message, msg)
                return current_assistant_index

        message = self._build_message(
            message_id=message_id,
            role="assistant",
            agent="claude",
            time_created=timestamp_ms,
            parts=[part],
        )
        self._apply_assistant_metadata(message, msg)
        messages.append(message)
        return len(messages) - 1

    def _append_assistant_text(
        self,
        messages: list[dict[str, Any]],
        *,
        message_id: str,
        msg: dict[str, Any],
        timestamp_ms: int,
        part: dict[str, Any],
        current_assistant_index: int | None,
    ) -> int:
        """Append text to the active assistant group or create a new one."""
        if current_assistant_index is not None:
            message = messages[current_assistant_index]
            has_tool = self._message_has_part_type(message, "tool")
            if not has_tool:
                self._append_part_if_new(message, part)
                self._apply_assistant_metadata(message, msg)
                return current_assistant_index

        message = self._build_message(
            message_id=message_id,
            role="assistant",
            agent="claude",
            time_created=timestamp_ms,
            parts=[part],
        )
        self._apply_assistant_metadata(message, msg)
        messages.append(message)
        return len(messages) - 1

    def _attach_tool_call_to_latest_assistant(
        self,
        messages: list[dict[str, Any]],
        *,
        message_id: str,
        msg: dict[str, Any],
        timestamp_ms: int,
        latest_assistant_text_index: int | None,
        tool_part: dict[str, Any],
    ) -> tuple[int, int]:
        """Attach one tool part to the latest assistant text message or create a fallback one."""
        if latest_assistant_text_index is not None:
            message = messages[latest_assistant_text_index]
            message["parts"].append(tool_part)
            self._apply_assistant_metadata(message, msg)
            return latest_assistant_text_index, len(message["parts"]) - 1

        message = self._build_message(
            message_id=message_id,
            role="assistant",
            agent="claude",
            time_created=timestamp_ms,
            mode="tool",
            parts=[tool_part],
        )
        self._apply_assistant_metadata(message, msg)
        messages.append(message)
        return len(messages) - 1, 0

    def _should_ignore_tool(self, tool_name: str) -> bool:
        """Whether a Claude tool should be hidden from export."""
        return tool_name == "TodoWrite"

    def _extract_tool_state_updates(self, tool_use_result: Any) -> dict[str, Any]:
        """Extract status-like fields from a Claude tool result wrapper."""
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
        messages: list[dict[str, Any]],
        pending_tool_calls: dict[str, tuple[int, int]],
        *,
        call_id: str,
        output_parts: list[dict[str, Any]],
        state_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Backfill tool output and state updates into a matching tool part."""
        if not call_id:
            return False

        location = pending_tool_calls.get(call_id)
        if location is None:
            return False

        message_index, part_index = location
        state = messages[message_index]["parts"][part_index].setdefault("state", {})

        if output_parts:
            existing_output = state.get("output")
            if isinstance(existing_output, list):
                existing_output.extend(output_parts)
            elif existing_output is None:
                state["output"] = list(output_parts)
            else:
                state["output"] = [existing_output, *output_parts]

        if state_updates:
            state.update(state_updates)

        if output_parts and "status" not in state:
            state["status"] = "completed"

        return bool(output_parts or state_updates)

    def _build_fallback_tool_message(
        self,
        *,
        message_id: str,
        timestamp_ms: int,
        tool_call_id: str | None,
        output_parts: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Build fallback tool message for unmatched tool output."""
        if not output_parts:
            return None

        extra = {"tool_call_id": tool_call_id} if tool_call_id else None
        return self._build_message(
            message_id=message_id,
            role="tool",
            time_created=timestamp_ms,
            parts=output_parts,
            extra=extra,
        )

    def _resolve_tool_call_id(
        self,
        data: dict[str, Any],
        item: dict[str, Any],
        assistant_uuid_to_tool_calls: dict[str, list[str]],
    ) -> str:
        """Resolve a tool_result item to a tool call id."""
        tool_call_id = str(item.get("tool_use_id", "")).strip()
        if tool_call_id:
            return tool_call_id

        source_uuid = str(data.get("sourceToolAssistantUUID", "")).strip()
        if not source_uuid:
            return ""

        tool_call_ids = assistant_uuid_to_tool_calls.get(source_uuid, [])
        if len(tool_call_ids) == 1:
            return tool_call_ids[0]
        return ""

    def _convert_assistant_record(
        self,
        data: dict[str, Any],
        messages: list[dict[str, Any]],
        pending_tool_calls: dict[str, tuple[int, int]],
        ignored_tool_call_ids: set[str],
        assistant_uuid_to_tool_calls: dict[str, list[str]],
        assistant_state: dict[str, int | None],
    ) -> None:
        """Convert one Claude assistant record."""
        msg = data.get("message", {})
        timestamp_ms = self._parse_timestamp_ms(data)
        raw_content = msg.get("content", [])

        tool_call_ids: list[str] = []
        current_assistant_index = assistant_state.get("current_index")
        latest_assistant_text_index = assistant_state.get("latest_text_index")

        if isinstance(raw_content, list):
            for item in raw_content:
                if not isinstance(item, dict):
                    continue
                part_type = item.get("type")
                message_id = str(data.get("uuid", ""))
                if part_type == "thinking":
                    text = str(item.get("thinking", ""))
                    if text.strip():
                        current_assistant_index = self._append_assistant_reasoning(
                            messages,
                            message_id=message_id,
                            msg=msg,
                            timestamp_ms=timestamp_ms,
                            part=self._build_reasoning_part(text, timestamp_ms),
                            current_assistant_index=current_assistant_index,
                        )
                    continue

                if part_type == "text":
                    text = str(item.get("text", ""))
                    if text.strip():
                        current_assistant_index = self._append_assistant_text(
                            messages,
                            message_id=message_id,
                            msg=msg,
                            timestamp_ms=timestamp_ms,
                            part=self._build_text_part(text, timestamp_ms),
                            current_assistant_index=current_assistant_index,
                        )
                        latest_assistant_text_index = current_assistant_index
                    continue

                if part_type != "tool_use":
                    continue

                tool_name = str(item.get("name", "")).strip()
                tool_call_id = str(item.get("id", "")).strip()
                if tool_name and tool_call_id and self._should_ignore_tool(tool_name):
                    ignored_tool_call_ids.add(tool_call_id)
                    continue

                tool_part = self._build_tool_part(item, timestamp_ms)
                message_index, part_index = self._attach_tool_call_to_latest_assistant(
                    messages,
                    message_id=message_id,
                    msg=msg,
                    timestamp_ms=timestamp_ms,
                    latest_assistant_text_index=latest_assistant_text_index,
                    tool_part=tool_part,
                )
                current_assistant_index = message_index
                if tool_call_id:
                    pending_tool_calls[tool_call_id] = (message_index, part_index)
                    tool_call_ids.append(tool_call_id)

        if tool_call_ids:
            assistant_uuid_to_tool_calls[str(data.get("uuid", ""))] = tool_call_ids

        assistant_state["current_index"] = current_assistant_index
        assistant_state["latest_text_index"] = latest_assistant_text_index

    def _convert_user_record(
        self,
        data: dict[str, Any],
        messages: list[dict[str, Any]],
        pending_tool_calls: dict[str, tuple[int, int]],
        ignored_tool_call_ids: set[str],
        assistant_uuid_to_tool_calls: dict[str, list[str]],
        assistant_state: dict[str, int | None],
    ) -> None:
        """Convert one Claude user record."""
        msg = data.get("message", {})
        timestamp_ms = self._parse_timestamp_ms(data)
        content = msg.get("content", "")

        if isinstance(content, str):
            parts = self._normalize_user_text_parts(content, timestamp_ms)
            if not parts:
                return
            messages.append(
                self._build_message(
                    message_id=str(data.get("uuid", "")),
                    role="user",
                    time_created=timestamp_ms,
                    parts=parts,
                )
            )
            assistant_state["current_index"] = None
            assistant_state["latest_text_index"] = None
            return

        if not isinstance(content, list):
            assistant_state["current_index"] = None
            assistant_state["latest_text_index"] = None
            return

        visible_parts = self._normalize_user_text_parts(content, timestamp_ms)
        tool_state_updates = self._extract_tool_state_updates(data.get("toolUseResult"))

        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue

            tool_call_id = self._resolve_tool_call_id(data, item, assistant_uuid_to_tool_calls)
            if tool_call_id and tool_call_id in ignored_tool_call_ids:
                continue

            output_parts = self._normalize_claude_tool_output(item.get("content"), timestamp_ms)
            if self._backfill_tool_output(
                messages,
                pending_tool_calls,
                call_id=tool_call_id,
                output_parts=output_parts,
                state_updates=tool_state_updates,
            ):
                continue

            fallback_message = self._build_fallback_tool_message(
                message_id=str(data.get("uuid", "")),
                timestamp_ms=timestamp_ms,
                tool_call_id=tool_call_id or None,
                output_parts=output_parts,
            )
            if fallback_message:
                messages.append(fallback_message)

        if visible_parts:
            messages.append(
                self._build_message(
                    message_id=str(data.get("uuid", "")),
                    role="user",
                    time_created=timestamp_ms,
                    parts=visible_parts,
                )
            )

        assistant_state["current_index"] = None
        assistant_state["latest_text_index"] = None

    def _convert_to_opencode_format(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a single Claude record into unified message format."""
        messages: list[dict[str, Any]] = []
        assistant_state: dict[str, int | None] = {
            "current_index": None,
            "latest_text_index": None,
        }
        self._convert_claude_record(data, messages, {}, set(), {}, assistant_state)
        if not messages:
            return None
        return messages[0]

    def _convert_claude_record(
        self,
        data: dict[str, Any],
        messages: list[dict[str, Any]],
        pending_tool_calls: dict[str, tuple[int, int]],
        ignored_tool_call_ids: set[str],
        assistant_uuid_to_tool_calls: dict[str, list[str]],
        assistant_state: dict[str, int | None],
    ) -> None:
        """Convert one Claude jsonl record and update parser state."""
        if data.get("isMeta") is True:
            return

        msg_type = data.get("type", "")

        if msg_type == "assistant":
            self._convert_assistant_record(
                data,
                messages,
                pending_tool_calls,
                ignored_tool_call_ids,
                assistant_uuid_to_tool_calls,
                assistant_state,
            )
            return

        if msg_type == "user":
            self._convert_user_record(
                data,
                messages,
                pending_tool_calls,
                ignored_tool_call_ids,
                assistant_uuid_to_tool_calls,
                assistant_state,
            )
            return

        if msg_type != "tool_result":
            return

        timestamp_ms = self._parse_timestamp_ms(data)
        msg = data.get("message", {})
        output_parts = self._normalize_claude_tool_output(msg.get("content"), timestamp_ms)
        fallback_message = self._build_fallback_tool_message(
            message_id=str(data.get("uuid", "")),
            timestamp_ms=timestamp_ms,
            tool_call_id=None,
            output_parts=output_parts,
        )
        if fallback_message:
            messages.append(fallback_message)
        assistant_state["current_index"] = None
        assistant_state["latest_text_index"] = None
