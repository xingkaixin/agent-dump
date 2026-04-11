"""
Codex agent handler
"""

from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.message_filter import filter_messages_for_export, is_developer_like_user_message
from agent_dump.paths import ProviderRoots, first_existing_path

CODEX_TOOL_TITLE_MAP = {
    "exec_command": "bash",
    "apply_patch": "patch",
    "patch": "patch",
    "subagent": "subagent",
}
PROPOSED_PLAN_PATTERN = re.compile(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", re.DOTALL)
SKILL_NAME_PATTERN = re.compile(r"<name>\s*(.*?)\s*</name>", re.DOTALL)
SUBAGENT_NOTIFICATION_PATTERN = re.compile(r"<subagent_notification>\s*(.*?)\s*</subagent_notification>", re.DOTALL)
PLAN_APPROVAL_PREFIX = "PLEASE IMPLEMENT THIS PLAN"


class CodexAgent(BaseAgent):
    """Handler for Codex sessions"""

    def __init__(self):
        super().__init__("codex", "Codex")
        self.base_path: Path | None = None
        self._titles_cache: dict[str, str] | None = None

    def _find_base_path(self) -> Path | None:
        """Find the Codex sessions directory"""
        roots = ProviderRoots.from_env_or_home()
        return first_existing_path(roots.codex_root / "sessions", Path("data/codex"))

    def _load_titles_cache(self) -> dict[str, str]:
        """Load session titles from global state file"""
        if self._titles_cache is not None:
            return self._titles_cache

        titles: dict[str, str] = {}
        roots = ProviderRoots.from_env_or_home()
        global_state_path = roots.codex_root / ".codex-global-state.json"

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
                if session and self._normalize_datetime_utc(session.created_at) >= cutoff_time:
                    sessions.append(session)
            except Exception as e:
                print(f"警告: 解析会话文件失败 {jsonl_file}: {e}")
                continue

        return sorted(sessions, key=lambda s: self._normalize_datetime_utc(s.created_at), reverse=True)

    def _normalize_datetime_utc(self, value: datetime) -> datetime:
        """Normalize datetime to timezone-aware UTC for safe comparisons."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

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

    def _extract_scan_metadata(
        self, lines: list[str], fallback_created_at: datetime
    ) -> tuple[datetime, int, str | None]:
        """Extract lightweight summary metadata without building full session data."""
        updated_at = fallback_created_at
        message_count = 0
        model: str | None = None

        for line in lines:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp_str = str(data.get("timestamp", "")).strip()
            if timestamp_str:
                with suppress(ValueError):
                    updated_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                continue

            payload_type = payload.get("type")
            if payload_type == "message" or payload_type in {"function_call", "function_call_output"}:
                message_count += 1

            if model is None:
                payload_model = payload.get("model")
                if isinstance(payload_model, str) and payload_model.strip():
                    model = payload_model.strip()
                    continue

                arguments = payload.get("arguments")
                if isinstance(arguments, dict):
                    model_arg = arguments.get("model")
                    if isinstance(model_arg, str) and model_arg.strip():
                        model = model_arg.strip()

        return updated_at, message_count, model

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

            updated_at, message_count, model = self._extract_scan_metadata(lines, created_at)

            return Session(
                id=session_id,
                title=title,
                created_at=created_at,
                updated_at=updated_at,
                source_path=file_path,
                metadata={
                    "cwd": payload.get("cwd", ""),
                    "cli_version": payload.get("cli_version", ""),
                    "model_provider": payload.get("model_provider", ""),
                    "model": model or payload.get("model_provider", ""),
                    "message_count": message_count,
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

    def _empty_stats(self) -> dict[str, int]:
        return {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "message_count": 0,
        }

    def _accumulate_token_stats(self, stats: dict[str, int], data: dict[str, Any]) -> None:
        """Update stats from one raw record when token usage is present."""
        if "token_count" not in str(data):
            return

        info = data.get("payload", {}).get("info", {})
        if not info:
            return

        token_usage = info.get("total_token_usage", {})
        stats["total_input_tokens"] += token_usage.get("input_tokens", 0)
        stats["total_output_tokens"] += token_usage.get("output_tokens", 0)

    def _prepare_json_export_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        transformed_messages = self._transform_skill_messages_for_json_export(messages)
        json_messages = self._filter_json_export_only_tools(transformed_messages)
        return filter_messages_for_export(json_messages)

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary"""
        if not session.source_path.exists():
            raise FileNotFoundError(f"Session file not found: {session.source_path}")

        messages: list[dict[str, Any]] = []
        pending_tool_calls: dict[str, tuple[int, int]] = {}
        subagent_call_map: dict[str, dict[str, str]] = {}
        subagent_nicknames: dict[str, str] = {}
        current_assistant_index: int | None = None
        latest_assistant_text_index: int | None = None
        pending_plan_location: tuple[int, int] | None = None
        stats = self._empty_stats()

        with open(session.source_path, encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    current_assistant_index, latest_assistant_text_index, pending_plan_location = (
                        self._convert_record_to_messages(
                            data=data,
                            messages=messages,
                            pending_tool_calls=pending_tool_calls,
                            subagent_call_map=subagent_call_map,
                            subagent_nicknames=subagent_nicknames,
                            current_assistant_index=current_assistant_index,
                            latest_assistant_text_index=latest_assistant_text_index,
                            pending_plan_location=pending_plan_location,
                        )
                    )
                    self._accumulate_token_stats(stats, data)
                except Exception as e:
                    print(f"警告: 转换消息格式失败: {e}")
                    continue

        self._finalize_pending_plan(messages, pending_plan_location)

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

    def get_session_head(self, session: Session) -> dict[str, Any]:
        head = super().get_session_head(session)
        message_count = 0

        with open(session.source_path, encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                payload = data.get("payload", {})
                if payload.get("type") == "message":
                    message_count += 1

                model = payload.get("model")
                if isinstance(model, str) and model.strip() and not head.get("model"):
                    head["model"] = model.strip()

        head["message_count"] = message_count
        return head

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format"""
        session_data = self.get_session_data(session)
        messages = session_data.get("messages")
        if isinstance(messages, list):
            session_data["messages"] = self._prepare_json_export_messages(messages)

        output_dir.mkdir(parents=True, exist_ok=True)
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

    def _filter_json_export_only_tools(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter Codex-only tool parts that should not appear in JSON export."""
        filtered_messages: list[dict[str, Any]] = []

        for message in messages:
            parts = message.get("parts", [])
            if not isinstance(parts, list):
                filtered_messages.append(message)
                continue

            filtered_parts = [
                part
                for part in parts
                if not (isinstance(part, dict) and part.get("type") == "tool" and part.get("tool") == "wait_agent")
            ]
            if not filtered_parts:
                continue

            next_message = dict(message)
            next_message["parts"] = filtered_parts
            if all(isinstance(part, dict) and part.get("type") == "tool" for part in filtered_parts):
                next_message["mode"] = "tool"
            elif next_message.get("mode") == "tool":
                next_message["mode"] = None
            filtered_messages.append(next_message)

        return filtered_messages

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

    def _try_parse_json_string(self, value: Any) -> Any | None:
        """Parse a JSON string and return None when it is not valid JSON."""
        if not isinstance(value, str):
            return None

        stripped = value.strip()
        if not stripped:
            return None

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

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

    def _build_plan_part(self, plan_text: str, timestamp_ms: int) -> dict[str, Any]:
        """Build one plan part."""
        return {
            "type": "plan",
            "input": plan_text,
            "output": None,
            "approval_status": "fail",
            "time_created": timestamp_ms,
        }

    def _build_tool_part(
        self,
        *,
        tool_name: str,
        call_id: str,
        arguments: Any,
        timestamp_ms: int,
    ) -> dict[str, Any]:
        """Build one unified tool part."""
        return {
            "type": "tool",
            "tool": tool_name,
            "callID": call_id,
            "title": self._map_tool_title(tool_name),
            "state": {"arguments": arguments},
            "time_created": timestamp_ms,
        }

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

        return self._build_message(
            message_id=message_id,
            role="assistant",
            time_created=timestamp_ms,
            parts=[self._build_text_part(str(notification.get("text", "")), timestamp_ms)],
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

        return self._build_message(
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

    def _build_function_tool_part(self, payload: dict[str, Any], timestamp_ms: int) -> dict[str, Any]:
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

    def _build_custom_tool_part(self, payload: dict[str, Any], timestamp_ms: int) -> dict[str, Any]:
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

    def _build_empty_patch_arguments(self, raw_input: str, parse_error: str | None = None) -> dict[str, Any]:
        """Build the default apply_patch arguments payload."""
        arguments = {
            "kind": "apply_patch",
            "raw": raw_input,
            "content": [],
        }
        if parse_error:
            arguments["parse_error"] = parse_error
        return arguments

    def _normalize_custom_tool_arguments(self, tool_name: str, raw_input: Any) -> Any:
        """Normalize custom tool input."""
        if tool_name == "apply_patch":
            return self._parse_apply_patch_input(str(raw_input or ""))
        return raw_input

    def _is_patch_operation_header(self, line: str) -> bool:
        """Whether one line starts a new apply_patch operation."""
        return line.startswith(
            (
                "*** Add File: ",
                "*** Delete File: ",
                "*** Update File: ",
                "*** End Patch",
            )
        )

    def _build_patch_operation(
        self,
        *,
        action: str,
        path: str,
        old_path: str | None = None,
    ) -> dict[str, Any]:
        """Build one structured patch operation."""
        return {
            "action": action,
            "path": path,
            "old_path": old_path,
            "hunks": [],
        }

    def _append_patch_line(
        self,
        operation: dict[str, Any],
        *,
        header: str | None,
        kind: str,
        text: str,
    ) -> None:
        """Append one line to the current patch hunk, creating it when needed."""
        hunks = operation["hunks"]
        if not hunks or hunks[-1]["header"] != header:
            hunks.append({"header": header, "lines": []})
        hunks[-1]["lines"].append({"kind": kind, "text": text})

    def _parse_patch_hunks(self, lines: list[str], start_index: int, operation: dict[str, Any]) -> int:
        """Parse all hunks for one apply_patch operation."""
        index = start_index
        current_header: str | None = None

        while index < len(lines):
            line = lines[index]
            if self._is_patch_operation_header(line):
                break
            if line == "*** End of File":
                index += 1
                continue
            if line.startswith("@@"):
                current_header = line
                if not operation["hunks"] or operation["hunks"][-1]["header"] != current_header:
                    operation["hunks"].append({"header": current_header, "lines": []})
                index += 1
                continue
            if line.startswith("+"):
                self._append_patch_line(operation, header=current_header, kind="add", text=line[1:])
                index += 1
                continue
            if line.startswith("-"):
                self._append_patch_line(operation, header=current_header, kind="remove", text=line[1:])
                index += 1
                continue
            if line.startswith(" "):
                self._append_patch_line(operation, header=current_header, kind="context", text=line[1:])
                index += 1
                continue
            raise ValueError(f"无法解析 patch 行: {line}")

        return index

    def _build_write_file_content(self, operation: dict[str, Any]) -> str:
        """Build final file content for an added file."""
        lines: list[str] = []
        for hunk in operation["hunks"]:
            for line in hunk["lines"]:
                if line["kind"] == "remove":
                    continue
                lines.append(line["text"])
        return "\n".join(lines)

    def _build_edit_file_diff(self, operation: dict[str, Any]) -> str:
        """Build one unified diff string for an edited file."""
        source_path = operation.get("old_path") or operation["path"]
        target_path = operation["path"]
        diff_lines = [
            f"Index: {target_path}",
            "===================================================================",
            f"--- {source_path}",
            f"+++ {target_path}",
        ]

        for hunk in operation["hunks"]:
            header = hunk.get("header")
            if header:
                diff_lines.append(header)
            for line in hunk["lines"]:
                prefix = {
                    "remove": "-",
                    "add": "+",
                    "context": " ",
                }.get(line["kind"], "")
                diff_lines.append(f"{prefix}{line['text']}")

        return "\n".join(diff_lines)

    def _build_patch_content_blocks(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert parsed patch operations into exported content blocks."""
        blocks: list[dict[str, Any]] = []

        for operation in operations:
            action = operation["action"]
            path = operation["path"]
            old_path = operation.get("old_path")

            if action == "add":
                blocks.append(
                    {
                        "type": "write_file",
                        "path": path,
                        "old_path": None,
                        "input": {"content": self._build_write_file_content(operation)},
                    }
                )
                continue

            if action == "delete":
                blocks.append(
                    {
                        "type": "delete_file",
                        "path": path,
                        "old_path": None,
                        "input": {"content": ""},
                    }
                )
                continue

            if action == "move":
                blocks.append(
                    {
                        "type": "move_file",
                        "path": path,
                        "old_path": old_path,
                        "input": {"content": ""},
                    }
                )
                continue

            blocks.append(
                {
                    "type": "edit_file",
                    "path": path,
                    "old_path": old_path,
                    "input": {"content": self._build_edit_file_diff(operation)},
                }
            )

        return blocks

    def _parse_apply_patch_input(self, raw_input: str) -> dict[str, Any]:
        """Parse apply_patch input into a structured patch payload."""
        result = self._build_empty_patch_arguments(raw_input)
        lines = raw_input.splitlines()

        try:
            if not lines:
                raise ValueError("patch 为空")
            if lines[0] != "*** Begin Patch":
                raise ValueError("patch 缺少 Begin Patch 头")

            index = 1
            operations: list[dict[str, Any]] = []
            saw_end_patch = False

            while index < len(lines):
                line = lines[index]
                if line == "*** End Patch":
                    saw_end_patch = True
                    index += 1
                    break
                if line.startswith("*** Add File: "):
                    path = line.removeprefix("*** Add File: ")
                    operation = self._build_patch_operation(action="add", path=path)
                    index = self._parse_patch_hunks(lines, index + 1, operation)
                    operations.append(operation)
                    continue
                if line.startswith("*** Delete File: "):
                    path = line.removeprefix("*** Delete File: ")
                    operation = self._build_patch_operation(action="delete", path=path)
                    index = self._parse_patch_hunks(lines, index + 1, operation)
                    operations.append(operation)
                    continue
                if line.startswith("*** Update File: "):
                    old_path = line.removeprefix("*** Update File: ")
                    index += 1
                    new_path = old_path
                    if index < len(lines) and lines[index].startswith("*** Move to: "):
                        new_path = lines[index].removeprefix("*** Move to: ")
                        index += 1

                    operation = self._build_patch_operation(
                        action="move" if new_path != old_path else "update",
                        path=new_path,
                        old_path=old_path if new_path != old_path else None,
                    )
                    index = self._parse_patch_hunks(lines, index, operation)
                    if operation["old_path"] and operation["hunks"]:
                        operation["action"] = "update"
                    operations.append(operation)
                    continue
                raise ValueError(f"无法解析 patch 操作头: {line}")

            if not saw_end_patch:
                raise ValueError("patch 缺少 End Patch 尾")

            result["content"] = self._build_patch_content_blocks(operations)
            return result
        except ValueError as exc:
            return self._build_empty_patch_arguments(raw_input, parse_error=str(exc))

    def _normalize_output_parts(self, output: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        """Normalize tool output into text parts."""
        if output is None:
            return []
        if isinstance(output, str):
            return [self._build_text_part(output, timestamp_ms)]
        if isinstance(output, (dict, list)):
            return [self._build_text_part(json.dumps(output, ensure_ascii=False, indent=2), timestamp_ms)]
        return [self._build_text_part(str(output), timestamp_ms)]

    def _normalize_custom_tool_output(self, output: Any, timestamp_ms: int) -> list[dict[str, Any]]:
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

    def _extract_message_content_parts(self, role: str, content: Any, timestamp_ms: int) -> list[dict[str, Any]]:
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
            text = str(item.get("text", ""))
            if is_assistant:
                plan_text = self._extract_proposed_plan_content(text)
                if plan_text is not None:
                    parts.append(self._build_plan_part(plan_text, timestamp_ms))
                    continue
            parts.append(self._build_text_part(text, timestamp_ms))

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

    def _finalize_pending_plan(
        self,
        messages: list[dict[str, Any]],
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
        plan_part["approval_status"] = approval_status
        plan_part["output"] = output

    def _message_contains_plan_part(self, message: dict[str, Any]) -> bool:
        """Whether one message contains a plan part."""
        return self._message_has_part_type(message, "plan")

    def _extract_visible_user_text(self, parts: list[dict[str, Any]]) -> str | None:
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

    def _is_plan_approval_user_message(self, parts: list[dict[str, Any]]) -> tuple[bool, str | None]:
        """Whether one user message should be consumed as plan approval input."""
        user_text = self._extract_visible_user_text(parts)
        if user_text is None:
            return False, None

        if is_developer_like_user_message("user", [user_text]):
            return False, None

        return True, user_text

    def _attach_tool_part_to_latest_assistant(
        self,
        messages: list[dict[str, Any]],
        tool_part: dict[str, Any],
        timestamp_ms: int,
        latest_assistant_text_index: int | None,
    ) -> tuple[int, int]:
        """Attach one tool call to the latest assistant text message or create a fallback one."""
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

    def _attach_tool_call_to_latest_assistant(
        self,
        messages: list[dict[str, Any]],
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
        messages: list[dict[str, Any]],
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
        messages: list[dict[str, Any]],
        pending_tool_calls: dict[str, tuple[int, int]],
        *,
        call_id: str,
        output_parts: list[dict[str, Any]],
        raw_output: Any,
        subagent_call_map: dict[str, dict[str, str]],
        subagent_nicknames: dict[str, str],
    ) -> bool:
        """Backfill tool output to its matching tool part."""
        if not call_id or not output_parts:
            return False

        location = pending_tool_calls.get(call_id)
        if location is None:
            return False

        message_index, part_index = location
        tool_part = messages[message_index]["parts"][part_index]
        state = tool_part.setdefault("state", {})
        existing_output = state.get("output")
        if isinstance(existing_output, list):
            existing_output.extend(output_parts)
        elif existing_output is None:
            state["output"] = list(output_parts)
        else:
            state["output"] = [existing_output, *output_parts]
        self._record_subagent_output(
            tool_part=tool_part,
            output_parts=output_parts,
            raw_output=raw_output,
            call_id=call_id,
            subagent_call_map=subagent_call_map,
            subagent_nicknames=subagent_nicknames,
        )
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
        subagent_call_map: dict[str, dict[str, str]],
        subagent_nicknames: dict[str, str],
        current_assistant_index: int | None,
        latest_assistant_text_index: int | None,
        pending_plan_location: tuple[int, int] | None,
    ) -> tuple[int | None, int | None, tuple[int, int] | None]:
        """Convert one Codex record into unified messages while preserving stream relationships."""
        msg_type = data.get("type", "")
        payload = data.get("payload", {})
        timestamp_ms = self._parse_timestamp_ms(data)
        message_id = str(data.get("timestamp", ""))

        if msg_type == "session_meta":
            return current_assistant_index, latest_assistant_text_index, pending_plan_location

        if msg_type == "response_item":
            item_type = payload.get("type", "")

            if item_type == "message":
                role = str(payload.get("role", "unknown"))
                parts = self._extract_message_content_parts(role, payload.get("content", []), timestamp_ms)
                if not parts:
                    return current_assistant_index, latest_assistant_text_index, pending_plan_location

                if role == "assistant":
                    if pending_plan_location is not None:
                        self._finalize_pending_plan(messages, pending_plan_location)
                        pending_plan_location = None

                    assistant_index = self._append_assistant_text(
                        messages,
                        message_id=message_id,
                        timestamp_ms=timestamp_ms,
                        parts=parts,
                        current_assistant_index=current_assistant_index,
                    )
                    next_index = assistant_index if assistant_index is not None else current_assistant_index
                    next_latest_text_index = next_index
                    if assistant_index is not None and self._message_contains_plan_part(messages[assistant_index]):
                        pending_plan_location = (assistant_index, len(messages[assistant_index]["parts"]) - 1)
                        next_latest_text_index = None
                    return next_index, next_latest_text_index, pending_plan_location

                can_consume_for_plan, user_text = self._is_plan_approval_user_message(parts)
                if pending_plan_location is not None and can_consume_for_plan and user_text is not None:
                    approval_status = "success" if user_text.lstrip().startswith(PLAN_APPROVAL_PREFIX) else "fail"
                    output = None if approval_status == "success" else user_text
                    self._finalize_pending_plan(
                        messages,
                        pending_plan_location,
                        approval_status=approval_status,
                        output=output,
                    )
                    return None, None, None

                subagent_message = self._maybe_build_subagent_notification_message(
                    message_id=message_id,
                    timestamp_ms=timestamp_ms,
                    role=role,
                    parts=parts,
                    subagent_nicknames=subagent_nicknames,
                )
                if subagent_message is not None:
                    messages.append(subagent_message)
                    return None, None, pending_plan_location

                messages.append(
                    self._build_message(
                        message_id=message_id,
                        role=role,
                        time_created=timestamp_ms,
                        parts=parts,
                    )
                )
                return None, None, pending_plan_location

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
                return next_index, latest_assistant_text_index, pending_plan_location

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
                return next_current_index, latest_assistant_text_index, pending_plan_location

            if item_type == "custom_tool_call":
                message_index, part_index = self._attach_custom_tool_call_to_latest_assistant(
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
                return next_current_index, latest_assistant_text_index, pending_plan_location

            if item_type == "function_call_output":
                call_id = str(payload.get("call_id", ""))
                output_parts = self._normalize_output_parts(payload.get("output"), timestamp_ms)
                if self._backfill_tool_output(
                    messages,
                    pending_tool_calls,
                    call_id=call_id,
                    output_parts=output_parts,
                    raw_output=payload.get("output"),
                    subagent_call_map=subagent_call_map,
                    subagent_nicknames=subagent_nicknames,
                ):
                    return current_assistant_index, latest_assistant_text_index, pending_plan_location

                fallback = self._build_fallback_tool_message(
                    message_id=message_id,
                    timestamp_ms=timestamp_ms,
                    call_id=call_id,
                    output_parts=output_parts,
                )
                if fallback:
                    messages.append(fallback)
                return current_assistant_index, latest_assistant_text_index, pending_plan_location

            if item_type == "custom_tool_call_output":
                call_id = str(payload.get("call_id", ""))
                output_parts = self._normalize_custom_tool_output(payload.get("output"), timestamp_ms)
                if self._backfill_tool_output(
                    messages,
                    pending_tool_calls,
                    call_id=call_id,
                    output_parts=output_parts,
                    raw_output=payload.get("output"),
                    subagent_call_map=subagent_call_map,
                    subagent_nicknames=subagent_nicknames,
                ):
                    return current_assistant_index, latest_assistant_text_index, pending_plan_location

                fallback = self._build_fallback_tool_message(
                    message_id=message_id,
                    timestamp_ms=timestamp_ms,
                    call_id=call_id,
                    output_parts=output_parts,
                )
                if fallback:
                    messages.append(fallback)
                return current_assistant_index, latest_assistant_text_index, pending_plan_location

            return current_assistant_index, latest_assistant_text_index, pending_plan_location

        if msg_type == "event_msg":
            return current_assistant_index, latest_assistant_text_index, pending_plan_location

        return current_assistant_index, latest_assistant_text_index, pending_plan_location
