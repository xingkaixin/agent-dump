"""
Codex agent handler
"""

from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import Lock
from typing import Any

from agent_dump.agents.base import Session
from agent_dump.agents.codex_enrichment import CodexMessageEnrichmentMixin
from agent_dump.agents.codex_patch import parse_apply_patch_input
from agent_dump.agents.file_sessions import FileSessionAgent
from agent_dump.agents.jsonl_scan import (
    JsonlObjectScan,
    parse_iso_timestamp_ms,
    parse_object_lines,
    read_jsonl_scan_metadata,
    skipped_records_diagnostic,
)
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
from agent_dump.agents.message_types import (
    NormalizedMessage,
    NormalizedPart,
    NormalizedSessionData,
    NormalizedSessionStats,
    is_plan_part,
)
from agent_dump.agents.title_fallback import basename_title, normalize_title_text, resolve_session_title
from agent_dump.coercion import safe_int
from agent_dump.diagnostics import source_missing
from agent_dump.i18n import Keys, i18n
from agent_dump.message_filter import filter_messages_for_export, is_developer_like_user_message
from agent_dump.paths import ProviderRoots, SearchRoot

CODEX_TOOL_TITLE_MAP = {
    "exec_command": "bash",
    "apply_patch": "patch",
    "patch": "patch",
    "subagent": "subagent",
}
PROPOSED_PLAN_PATTERN = re.compile(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", re.DOTALL)
PLAN_APPROVAL_PREFIX = "PLEASE IMPLEMENT THIS PLAN"


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


class CodexAgent(CodexMessageEnrichmentMixin, FileSessionAgent):
    """Handler for Codex sessions"""

    provider_name = "codex"
    provider_display_name = "Codex"

    def __init__(self) -> None:
        super().__init__()
        self._titles_cache: dict[str, str] | None = None
        self._titles_cache_lock = Lock()

    def _iter_session_files(self) -> Iterator[Path]:
        if self.base_path is None:
            return iter(())
        return self.base_path.rglob("*.jsonl")

    def _session_file_candidates(self, session_id: str) -> Iterable[Path]:
        if self.base_path is None:
            return ()
        # 文件名格式 rollout-{timestamp}-{sessionId}.jsonl
        return self.base_path.rglob(f"*-{session_id}.jsonl")

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        roots = ProviderRoots.from_env_or_home()
        return (
            SearchRoot("CODEX_HOME/sessions", roots.codex_root / "sessions"),
            SearchRoot("local development fallback", Path("data/codex")),
        )

    def _load_titles_cache(self) -> dict[str, str]:
        """Load session titles from session index."""
        if self._titles_cache is not None:
            return self._titles_cache

        with self._titles_cache_lock:
            if self._titles_cache is not None:
                return self._titles_cache

            titles: dict[str, str] = {}
            roots = ProviderRoots.from_env_or_home()
            session_index_path = roots.codex_root / "session_index.jsonl"

            if session_index_path.exists():
                try:
                    for data in JsonlObjectScan(session_index_path):
                        session_id = data.get("id")
                        thread_name = data.get("thread_name")
                        if isinstance(session_id, str) and session_id.strip() and isinstance(thread_name, str):
                            normalized = normalize_title_text(thread_name)
                            if normalized:
                                titles[session_id] = normalized
                except Exception as e:
                    self._report_diagnostic(Keys.WARN_TITLE_CACHE_FAILED, error=str(e))

            self._titles_cache = titles
            return titles

    def _get_session_title(self, session_id: str) -> str | None:
        """Get session title from session index by session ID."""
        titles = self._load_titles_cache()
        return titles.get(session_id)

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
        self, records: list[dict[str, Any]], fallback_created_at: datetime, *, scanned_all: bool
    ) -> tuple[datetime, int | None, str | None]:
        """Extract lightweight summary metadata without building full session data."""
        updated_at = fallback_created_at
        message_count = 0
        model: str | None = None

        for data in records:
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

        return updated_at, message_count if scanned_all else None, model

    def _parse_session_file(self, file_path: Path) -> Session | None:
        """Parse a single Codex session file"""
        scan = read_jsonl_scan_metadata(file_path, head_line_limit=10)
        # session_header 在首记录超过 head 窗口时给出空 dict：Claude/Codex 靠目录
        # 布局与文件名识别会话，首记录只提供元数据，缺了就走既有的 mtime/目录名回退
        first_line = scan.session_header
        if first_line is None:
            return None

        payload = first_line.get("payload", {})
        session_id = payload.get("id", "")
        timestamp_str = payload.get("timestamp", "")

        if not session_id:
            session_id = self._extract_session_id_from_filename(file_path)

        try:
            created_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            stat = file_path.stat()
            created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        explicit_title = self._get_session_title(session_id)
        message_title = self._extract_title_from_records(scan.head_records[:10])
        directory_title = basename_title(payload.get("cwd")) or basename_title(file_path.parent)
        title = resolve_session_title(explicit_title, message_title, directory_title)

        metadata_records = list(scan.head_records)
        if not scan.scanned_all and scan.tail_record is not None:
            metadata_records.append(scan.tail_record)
        updated_at, message_count, model = self._extract_scan_metadata(
            metadata_records,
            created_at,
            scanned_all=scan.scanned_all,
        )

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

    def _extract_title(self, lines: list[str]) -> str | None:
        """Extract title from the second user message in a session."""
        try:
            return self._extract_title_from_records(parse_object_lines(lines[:10]))
        except Exception as e:
            self._report_diagnostic(Keys.WARN_TITLE_EXTRACT_FAILED, error=str(e))

        return None

    def _extract_title_from_records(self, records: list[dict[str, Any]]) -> str | None:
        user_message_count = 0
        for data in records:
            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                continue

            if payload.get("type") != "message" or payload.get("role") != "user":
                continue

            user_message_count += 1
            if user_message_count < 2:
                continue

            content = payload.get("content", [])
            if not isinstance(content, list):
                continue

            text_fragments = []
            for item in content:
                if isinstance(item, dict):
                    text_fragments.append(str(item.get("text", "")))
                elif isinstance(item, str):
                    text_fragments.append(item)
            normalized = normalize_title_text(" ".join(text_fragments))
            if normalized:
                return normalized

        return None

    def _empty_stats(self) -> NormalizedSessionStats:
        return {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "message_count": 0,
        }

    def _accumulate_token_stats(self, stats: NormalizedSessionStats, data: dict[str, Any]) -> None:
        """Update stats from one raw record when token usage is present."""
        # 曾用 `"token_count" not in str(data)` 做前置过滤，但那会把每条记录（含数百 KB
        # 的工具输出）先 repr 成字符串再丢掉，比产生它的 json.loads 还贵。下面的结构化
        # 取值本身就是真实条件。
        payload = data.get("payload")
        info = payload.get("info") if isinstance(payload, dict) else None
        if not isinstance(info, dict):
            return

        token_usage = info.get("total_token_usage")
        if not isinstance(token_usage, dict):
            return
        stats["total_input_tokens"] += safe_int(token_usage.get("input_tokens"))
        stats["total_output_tokens"] += safe_int(token_usage.get("output_tokens"))

    def _prepare_json_export_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        transformed_messages = self._transform_skill_messages_for_json_export(messages)
        json_messages = self._filter_json_export_only_tools(transformed_messages)
        return filter_messages_for_export(json_messages)

    def get_session_data(self, session: Session) -> dict[str, Any]:
        """Get session data as a dictionary"""
        if not session.source_path.exists():
            raise source_missing(
                "session source file is missing",
                missing_path=session.source_path,
                searched_roots=[root.render() for root in self.get_search_roots()],
                next_steps=(
                    i18n.t(Keys.DIAG_STEP_CODEX_SESSION_LOCATION),
                    i18n.t(Keys.DIAG_STEP_LIST_TO_CHECK_ID),
                ),
            )

        state = _CodexAssemblyState()
        stats = self._empty_stats()

        scan = JsonlObjectScan(session.source_path)
        for data in scan:
            try:
                self._convert_record_to_messages(data=data, state=state)
                self._accumulate_token_stats(stats, data)
            except Exception as e:
                self._report_diagnostic(Keys.WARN_MESSAGE_CONVERT_FAILED, error=str(e))
                continue
        if diagnostic := skipped_records_diagnostic(scan):
            self._report_diagnostic(diagnostic.message_key, **diagnostic.fields)

        self._finalize_pending_plan(state.messages, state.pending_plan_location)

        stats["message_count"] = len(state.messages)

        session_data: NormalizedSessionData = {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": session.metadata.get("cwd", ""),
            "version": session.metadata.get("cli_version", ""),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": state.messages,
        }
        return dict(session_data)

    def _json_export_payload(self, session: Session) -> dict[str, Any]:
        """Apply Codex's JSON-export-only message transforms."""
        session_data = super()._json_export_payload(session)
        messages = session_data.get("messages")
        if isinstance(messages, list):
            session_data["messages"] = self._prepare_json_export_messages(messages)
        return session_data

    def _parse_timestamp_ms(self, data: dict[str, Any]) -> int:
        """Parse record timestamp into milliseconds."""
        return parse_iso_timestamp_ms(data.get("timestamp"))

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

    def _is_plan_approval_user_message(self, parts: list[NormalizedPart]) -> tuple[bool, str | None]:
        """Whether one user message should be consumed as plan approval input."""
        user_text = self._extract_visible_user_text(parts)
        if user_text is None:
            return False, None

        if is_developer_like_user_message("user", [user_text]):
            return False, None

        return True, user_text

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

        if role == "assistant":
            self._append_assistant_message_item(
                state,
                message_id=message_id,
                timestamp_ms=timestamp_ms,
                parts=parts,
            )
            return

        can_consume_for_plan, user_text = self._is_plan_approval_user_message(parts)
        if state.pending_plan_location is not None and can_consume_for_plan and user_text is not None:
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
