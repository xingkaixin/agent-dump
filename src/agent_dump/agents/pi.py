"""Pi agent handler."""

from collections.abc import Iterable, Iterator
from contextlib import suppress
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from agent_dump.agents.base import Session
from agent_dump.agents.file_sessions import FileSessionAgent
from agent_dump.agents.jsonl_scan import read_jsonl_scan_metadata
from agent_dump.agents.title_fallback import basename_title, normalize_title_text, resolve_session_title
from agent_dump.diagnostics import source_missing
from agent_dump.paths import ProviderRoots, SearchRoot

PI_TOOL_TITLE_MAP = {
    "bash": "bash",
    "edit": "edit",
    "grep": "grep",
    "read": "read",
    "write": "write",
}


class PiAgent(FileSessionAgent):
    """Handler for Pi coding agent sessions."""

    def __init__(self):
        super().__init__("pi", "Pi")

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        roots = ProviderRoots.from_env_or_home()
        return (
            SearchRoot("PI_HOME/agent/sessions", roots.pi_root / "agent" / "sessions"),
            SearchRoot("local development fallback", Path("data/pi")),
        )

    def _iter_session_files(self) -> Iterator[Path]:
        if self.base_path is None:
            return iter(())
        return self.base_path.rglob("*.jsonl")

    def _session_file_candidates(self, session_id: str) -> Iterable[Path]:
        if self.base_path is None:
            return ()
        # 文件名以 session id 结尾（如 20260101_{id}.jsonl）；header id 不一致时走全量扫描回退
        return self.base_path.rglob(f"*{session_id}.jsonl")

    def _parse_session_file(self, file_path: Path) -> Session | None:
        """Parse lightweight metadata from one Pi session file."""
        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)
        header = scan.first_record
        if not header or header.get("type") != "session":
            return None

        session_id = str(header.get("id") or file_path.stem).strip()
        if not session_id:
            return None

        stat = file_path.stat()
        fallback_created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        created_at = self._parse_datetime(header.get("timestamp")) or fallback_created_at

        metadata_records = list(scan.head_records)
        if not scan.scanned_all and scan.tail_record is not None:
            metadata_records.append(scan.tail_record)
        updated_at, message_count, model = self._extract_scan_metadata(
            metadata_records,
            created_at,
            scanned_all=scan.scanned_all,
        )
        explicit_title = self._extract_session_name(metadata_records)
        message_title = self._extract_title_from_records(scan.head_records)
        directory_title = basename_title(header.get("cwd")) or basename_title(file_path.parent)

        return Session(
            id=session_id,
            title=resolve_session_title(explicit_title, message_title, directory_title),
            created_at=created_at,
            updated_at=updated_at,
            source_path=file_path,
            metadata={
                "cwd": header.get("cwd", ""),
                "version": header.get("version"),
                "parent_session": header.get("parentSession"),
                "model": model,
                "message_count": message_count,
            },
        )

    def _extract_scan_metadata(
        self,
        records: list[dict[str, Any]],
        fallback_updated_at: datetime,
        *,
        scanned_all: bool,
    ) -> tuple[datetime, int | None, str | None]:
        updated_at = fallback_updated_at
        message_count = 0
        model: str | None = None

        for record in records:
            parsed_timestamp = self._parse_datetime(record.get("timestamp"))
            if parsed_timestamp and parsed_timestamp > updated_at:
                updated_at = parsed_timestamp

            if record.get("type") != "message":
                continue
            message_count += 1
            message = record.get("message")
            if isinstance(message, dict) and model is None:
                raw_model = message.get("model")
                if isinstance(raw_model, str) and raw_model.strip():
                    model = raw_model.strip()

        return updated_at, message_count if scanned_all else None, model

    def _extract_session_name(self, records: list[dict[str, Any]]) -> str | None:
        for record in reversed(records):
            if record.get("type") != "session_info":
                continue
            raw_name = record.get("name")
            name = normalize_title_text(raw_name) if isinstance(raw_name, str) else None
            if name:
                return name
        return None

    def _extract_title_from_records(self, records: list[dict[str, Any]]) -> str | None:
        for record in records:
            if record.get("type") != "message":
                continue
            message = record.get("message")
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            title = normalize_title_text(self._content_to_text(message.get("content")))
            if title:
                return title
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        with suppress(ValueError):
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return None

    def _parse_timestamp_ms(self, *values: Any) -> int:
        for value in values:
            parsed = self._parse_datetime(value)
            if parsed is not None:
                return int(parsed.timestamp() * 1000)
        return 0

    def get_session_head(self, session: Session) -> dict[str, Any]:
        head = super().get_session_head(session)
        message_count = 0
        model = head.get("model")

        with open(session.source_path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "message":
                    continue
                message_count += 1
                message = record.get("message")
                if isinstance(message, dict) and not model:
                    raw_model = message.get("model")
                    if isinstance(raw_model, str) and raw_model.strip():
                        model = raw_model.strip()

        head["message_count"] = message_count
        head["model"] = model
        return head

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary."""
        if not session.source_path.exists():
            raise source_missing(
                "session source file is missing",
                missing_path=session.source_path,
                searched_roots=[root.render() for root in self.get_search_roots()],
                next_steps=(
                    "确认 Pi 会话文件仍在 `PI_HOME/agent/sessions` 或本地开发数据目录。",
                    "重新运行 `agent-dump --list` 确认会话 ID 是否仍存在。",
                ),
            )

        messages: list[dict[str, Any]] = []
        stats = self._empty_stats()
        header: dict[str, Any] = {}
        latest_session_name: str | None = None

        with open(session.source_path, encoding="utf-8") as f:
            for seq, line in enumerate(f, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"警告: 转换 Pi 记录失败: {e}", file=sys.stderr)
                    continue

                if record.get("type") == "session" and not header:
                    header = record
                    continue
                if record.get("type") == "session_info":
                    latest_session_name = normalize_title_text(record.get("name")) or latest_session_name

                message = self._convert_entry_to_message(record, seq)
                if message:
                    messages.append(message)
                self._accumulate_stats(stats, record)

        stats["message_count"] = len(messages)
        title = latest_session_name or session.title

        return {
            "id": session.id,
            "title": title,
            "slug": None,
            "directory": session.metadata.get("cwd") or header.get("cwd", ""),
            "version": session.metadata.get("version") or header.get("version"),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": messages,
        }

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format."""
        session_data = self.get_session_data(session)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{session.id}.json"
        output_path.write_text(json.dumps(session_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def _empty_stats(self) -> dict[str, int | float]:
        return {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "message_count": 0,
        }

    def _accumulate_stats(self, stats: dict[str, int | float], record: dict[str, Any]) -> None:
        if record.get("type") != "message":
            return
        message = record.get("message")
        if not isinstance(message, dict):
            return
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return

        stats["total_input_tokens"] += self._int_value(usage.get("input"))
        stats["total_output_tokens"] += self._int_value(usage.get("output"))
        stats["total_tokens"] += self._int_value(usage.get("totalTokens"))
        cost = usage.get("cost")
        if isinstance(cost, dict):
            stats["total_cost"] += self._float_value(cost.get("total"))

    def _int_value(self, value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        return 0

    def _float_value(self, value: Any) -> float:
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return float(value)
        return 0

    def _convert_entry_to_message(self, record: dict[str, Any], seq: int) -> dict[str, Any] | None:
        entry_type = record.get("type")
        timestamp_ms = self._parse_timestamp_ms(record.get("timestamp"))
        extra = self._entry_extra(record, entry_type)

        if entry_type == "message":
            message = record.get("message")
            if not isinstance(message, dict):
                return None
            return self._convert_agent_message(message, record, seq, timestamp_ms, extra)

        if entry_type == "compaction":
            summary = str(record.get("summary", "")).strip()
            if not summary:
                return None
            return self._build_message(
                message_id=self._entry_message_id(record, seq),
                role="compaction",
                parts=[self._build_text_part(summary, timestamp_ms)],
                time_created=timestamp_ms,
                extra=extra,
            )

        if entry_type == "branch_summary":
            summary = str(record.get("summary", "")).strip()
            if not summary:
                return None
            return self._build_message(
                message_id=self._entry_message_id(record, seq),
                role="branch_summary",
                parts=[self._build_text_part(summary, timestamp_ms)],
                time_created=timestamp_ms,
                extra=extra,
            )

        if entry_type == "custom_message":
            parts = self._normalize_content_parts(record.get("content"), timestamp_ms)
            if not parts:
                return None
            return self._build_message(
                message_id=self._entry_message_id(record, seq),
                role="custom",
                parts=parts,
                time_created=timestamp_ms,
                extra=extra,
            )

        return None

    def _convert_agent_message(
        self,
        message: dict[str, Any],
        record: dict[str, Any],
        seq: int,
        entry_timestamp_ms: int,
        extra: dict[str, Any],
    ) -> dict[str, Any] | None:
        role = str(message.get("role", "")).strip()
        timestamp_ms = self._parse_timestamp_ms(message.get("timestamp"), record.get("timestamp")) or entry_timestamp_ms

        if role == "bashExecution":
            command = str(message.get("command", "")).strip()
            output = str(message.get("output", ""))
            if not command and not output.strip():
                return None
            return self._build_message(
                message_id=self._entry_message_id(record, seq),
                role="tool",
                mode="tool",
                parts=[
                    self._build_tool_part(
                        tool_name="bash",
                        call_id=self._entry_message_id(record, seq),
                        arguments={"command": command},
                        output=[self._build_text_part(output, timestamp_ms)] if output.strip() else [],
                        timestamp_ms=timestamp_ms,
                    )
                ],
                time_created=timestamp_ms,
                extra=extra,
            )

        if role == "toolResult":
            parts = [
                self._build_tool_part(
                    tool_name=str(message.get("toolName", "tool")).strip() or "tool",
                    call_id=str(message.get("toolCallId", "")).strip() or self._entry_message_id(record, seq),
                    arguments={},
                    output=self._normalize_content_parts(message.get("content"), timestamp_ms),
                    timestamp_ms=timestamp_ms,
                    state_extra={"is_error": bool(message.get("isError", False))},
                )
            ]
            return self._build_message(
                message_id=self._entry_message_id(record, seq),
                role="tool",
                mode="tool",
                parts=parts,
                time_created=timestamp_ms,
                extra=extra,
            )

        if role == "branchSummary":
            text = str(message.get("summary", "")).strip()
            parts = [self._build_text_part(text, timestamp_ms)] if text else []
            normalized_role = "branch_summary"
        elif role == "compactionSummary":
            text = str(message.get("summary", "")).strip()
            parts = [self._build_text_part(text, timestamp_ms)] if text else []
            normalized_role = "compaction"
        elif role == "custom":
            parts = self._normalize_content_parts(message.get("content"), timestamp_ms)
            normalized_role = "custom"
        else:
            parts = self._normalize_content_parts(message.get("content"), timestamp_ms)
            normalized_role = role or "unknown"

        if not parts:
            return None

        return self._build_message(
            message_id=self._entry_message_id(record, seq),
            role=normalized_role,
            agent="pi" if normalized_role == "assistant" else None,
            mode="tool" if all(part.get("type") == "tool" for part in parts) else None,
            model=message.get("model") if isinstance(message.get("model"), str) else None,
            provider=message.get("provider") if isinstance(message.get("provider"), str) else None,
            parts=parts,
            time_created=timestamp_ms,
            extra=extra,
        )

    def _normalize_content_parts(self, content: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [self._build_text_part(content, timestamp_ms)] if content.strip() else []

        if not isinstance(content, list):
            return []

        parts: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(self._build_text_part(item, timestamp_ms))
                continue
            if not isinstance(item, dict):
                continue

            part_type = item.get("type")
            if part_type == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(self._build_text_part(text, timestamp_ms))
            elif part_type == "thinking":
                text = str(item.get("thinking", "")).strip()
                if text:
                    parts.append(self._build_text_part(text, timestamp_ms, part_type="reasoning"))
            elif part_type == "toolCall":
                tool_name = str(item.get("name", "")).strip()
                call_id = str(item.get("id", "")).strip()
                if tool_name and call_id:
                    parts.append(
                        self._build_tool_part(
                            tool_name=tool_name,
                            call_id=call_id,
                            arguments=item.get("arguments"),
                            output=None,
                            timestamp_ms=timestamp_ms,
                        )
                    )
            elif part_type == "image":
                mime_type = str(item.get("mimeType", "")).strip()
                parts.append(
                    {
                        "type": "image",
                        "mime_type": mime_type or None,
                        "data": item.get("data"),
                        "time_created": timestamp_ms,
                    }
                )

        return parts

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        fragments: list[str] = []
        for item in content:
            if isinstance(item, str):
                fragments.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    fragments.append(str(item.get("text", "")))
                elif item.get("type") == "thinking":
                    fragments.append(str(item.get("thinking", "")))
        return " ".join(fragment for fragment in fragments if fragment)

    def _build_message(
        self,
        *,
        message_id: str,
        role: str,
        parts: list[dict[str, Any]],
        time_created: int,
        agent: str | None = None,
        mode: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message = {
            "id": message_id,
            "role": role,
            "agent": agent,
            "mode": mode,
            "model": model,
            "provider": provider,
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
        return {
            "type": part_type,
            "text": text,
            "time_created": timestamp_ms,
        }

    def _build_tool_part(
        self,
        *,
        tool_name: str,
        call_id: str,
        arguments: Any,
        output: list[dict[str, Any]] | None,
        timestamp_ms: int,
        state_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = {
            "arguments": arguments if arguments is not None else {},
            "output": output,
        }
        if state_extra:
            state.update(state_extra)
        return {
            "type": "tool",
            "tool": tool_name,
            "callID": call_id,
            "title": PI_TOOL_TITLE_MAP.get(tool_name, tool_name),
            "state": state,
            "time_created": timestamp_ms,
        }

    def _entry_message_id(self, record: dict[str, Any], seq: int) -> str:
        entry_id = str(record.get("id", "")).strip()
        return entry_id or f"pi-{seq}"

    def _entry_extra(self, record: dict[str, Any], entry_type: Any) -> dict[str, Any]:
        extra: dict[str, Any] = {"entry_type": entry_type}
        entry_id = str(record.get("id", "")).strip()
        parent_id = record.get("parentId")
        if entry_id:
            extra["entry_id"] = entry_id
        if isinstance(parent_id, str) or parent_id is None:
            extra["parent_id"] = parent_id
        return extra
