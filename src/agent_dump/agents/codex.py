"""
Codex agent handler
"""

from collections.abc import Iterable, Iterator, Mapping
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from agent_dump.agents.base import Session
from agent_dump.agents.codex_enrichment import CodexMessageEnrichmentMixin
from agent_dump.agents.codex_transcript import CodexTranscriptDecoder
from agent_dump.agents.file_sessions import FileSessionAgent
from agent_dump.agents.jsonl_scan import (
    JsonlObjectScan,
    parse_object_lines,
    read_jsonl_scan_metadata,
    skipped_records_diagnostic,
)
from agent_dump.agents.message_types import (
    NormalizedSessionData,
    NormalizedSessionStats,
)
from agent_dump.agents.title_fallback import basename_title, normalize_title_text, resolve_session_title
from agent_dump.coercion import safe_int
from agent_dump.diagnostics import source_missing
from agent_dump.i18n import Keys, i18n
from agent_dump.message_filter import filter_messages_for_export
from agent_dump.paths import SearchRoot, resolve_env_path


def _codex_root() -> Path:
    return resolve_env_path("CODEX_HOME", Path.home() / ".codex")


class CodexAgent(CodexMessageEnrichmentMixin, FileSessionAgent):
    """Handler for Codex sessions"""

    provider_name = "codex"
    provider_display_name = "Codex"

    def __init__(self) -> None:
        super().__init__()
        self._titles_cache: dict[str, str] | None = None
        self._titles_cache_lock = Lock()
        self._transcript_decoder = CodexTranscriptDecoder()

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
        root = _codex_root()
        return (
            SearchRoot("CODEX_HOME/sessions", root / "sessions"),
            SearchRoot("local development fallback", Path("data/codex")),
        )

    def _prepare_session_operation(self) -> None:
        with self._titles_cache_lock:
            self._titles_cache = None

    def _load_titles_cache(self) -> dict[str, str]:
        """Load session titles from session index."""
        if self._titles_cache is not None:
            return self._titles_cache

        with self._titles_cache_lock:
            if self._titles_cache is not None:
                return self._titles_cache

            titles: dict[str, str] = {}
            session_index_path = _codex_root() / "session_index.jsonl"

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

        state = self._transcript_decoder.new_state()
        stats = self._empty_stats()

        scan = JsonlObjectScan(session.source_path)
        for data in scan:
            try:
                self._transcript_decoder.append_record(state, data)
                self._accumulate_token_stats(stats, data)
            except Exception as e:
                self._report_diagnostic(Keys.WARN_MESSAGE_CONVERT_FAILED, error=str(e))
                continue
        if diagnostic := skipped_records_diagnostic(scan):
            self._report_diagnostic(diagnostic.message_key, **diagnostic.fields)

        messages = self._transcript_decoder.finish(state)
        stats["message_count"] = len(messages)

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
            "messages": messages,
        }
        return dict(session_data)

    def _json_export_payload(
        self,
        session: Session,
        *,
        session_data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply Codex's JSON-export-only message transforms."""
        payload = super()._json_export_payload(session, session_data=session_data)
        messages = payload.get("messages")
        if isinstance(messages, list):
            payload["messages"] = self._prepare_json_export_messages(messages)
        return payload

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
