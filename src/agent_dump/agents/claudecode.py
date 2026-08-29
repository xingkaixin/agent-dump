"""
Claude Code agent handler
"""

from collections.abc import Iterable, Iterator
from contextlib import suppress
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any

from agent_dump.agents.base import Session
from agent_dump.agents.claude_transcript import ClaudeTranscriptDecoder
from agent_dump.agents.file_sessions import FileSessionAgent
from agent_dump.agents.jsonl_scan import (
    JsonlObjectScan,
    parse_object_lines,
    read_jsonl_scan_metadata,
    skipped_records_diagnostic,
)
from agent_dump.agents.message_types import NormalizedSessionData, NormalizedSessionStats
from agent_dump.agents.title_fallback import basename_title, normalize_title_text, resolve_session_title
from agent_dump.diagnostics import source_missing
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import ProviderRoots, SearchRoot


class ClaudeCodeAgent(FileSessionAgent):
    """Handler for Claude Code sessions"""

    provider_name = "claudecode"
    provider_display_name = "Claude Code"

    def __init__(self) -> None:
        super().__init__()
        self._sessions_index_cache: dict[Path, dict[str, dict[str, Any]]] = {}
        self._sessions_index_lock = Lock()

    def _iter_session_files(self) -> Iterator[Path]:
        # 会话文件位于 <base_path>/<project_dir>/<session_id>.jsonl
        if self.base_path is None:
            return
        for project_dir in self.base_path.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                if jsonl_file.name == "sessions-index.json":
                    continue
                yield jsonl_file

    def _session_file_candidates(self, session_id: str) -> Iterable[Path]:
        if self.base_path is None:
            return ()
        return self.base_path.glob(f"*/{session_id}.jsonl")

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        roots = ProviderRoots.from_env_or_home()
        return (
            SearchRoot("CLAUDE_CONFIG_DIR/projects", roots.claude_root / "projects"),
            SearchRoot("local development fallback", Path("data/claudecode")),
        )

    def _prepare_session_operation(self) -> None:
        with self._sessions_index_lock:
            self._sessions_index_cache.clear()

    def _load_sessions_index(self, project_dir: Path) -> dict[str, dict[str, Any]]:
        """Load sessions index for a project"""
        index_path = project_dir / "sessions-index.json"
        if not index_path.exists():
            return {}

        try:
            with open(index_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("sessions index root must be an object")
            entries = data.get("entries", [])
            if not isinstance(entries, list):
                raise ValueError("sessions index entries must be an array")
        except Exception as exc:
            self._report_diagnostic(Keys.WARN_TITLE_CACHE_FAILED, error=str(exc))
            return {}

        sessions_index: dict[str, dict[str, Any]] = {}
        skipped_count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                skipped_count += 1
                continue
            session_id = entry.get("sessionId")
            if not isinstance(session_id, str) or not session_id.strip():
                skipped_count += 1
                continue
            sessions_index[session_id] = entry

        if skipped_count:
            self._report_diagnostic(
                Keys.WARN_TITLE_CACHE_ENTRIES_SKIPPED,
                path=str(index_path),
                count=skipped_count,
            )
        return sessions_index

    def _project_sessions_index(self, project_dir: Path) -> dict[str, dict[str, Any]]:
        """Return a project's sessions index, loading it once per provider operation.

        缓存整张索引而不是逐条命中项：缺失 Session ID 同样命中缓存，否则每个缺失
        ID 都要在锁内重读并展开整个索引，S 个文件对 E 个条目就是 O(S·E)，还会把
        FileSessionAgent 的并行解析串行化。
        """
        cached = self._sessions_index_cache.get(project_dir)
        if cached is not None:
            return cached

        with self._sessions_index_lock:
            cached = self._sessions_index_cache.get(project_dir)
            if cached is None:
                cached = self._load_sessions_index(project_dir)
                self._sessions_index_cache[project_dir] = cached
        return cached

    def _get_session_metadata(self, session_id: str, project_dir: Path) -> dict[str, Any] | None:
        """Get session metadata from sessions-index.json"""
        return self._project_sessions_index(project_dir).get(session_id)

    def _extract_scan_metadata(
        self, records: list[dict[str, Any]], fallback_created_at: datetime, *, scanned_all: bool
    ) -> tuple[datetime, int | None, str | None]:
        """Extract lightweight summary metadata from Claude jsonl."""
        updated_at = fallback_created_at
        message_count = 0
        model: str | None = None

        for data in records:
            timestamp_str = str(data.get("timestamp", "")).strip()
            if timestamp_str:
                with suppress(ValueError):
                    updated_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

            message = data.get("message")
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            if isinstance(role, str) and role.strip():
                message_count += 1

            if model is None:
                message_model = message.get("model")
                if isinstance(message_model, str) and message_model.strip():
                    model = message_model.strip()

        return updated_at, message_count if scanned_all else None, model

    def _parse_session_file(self, file_path: Path) -> Session | None:
        """Parse a single Claude Code session file"""
        project_dir = file_path.parent
        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)
        # session_header 在首记录超过 head 窗口时给出空 dict：Claude/Codex 靠目录
        # 布局与文件名识别会话，首记录只提供元数据，缺了就走既有的 mtime/目录名回退
        first_line = scan.session_header
        if first_line is None:
            return None

        session_id = file_path.stem
        timestamp_str = first_line.get("timestamp", "")

        try:
            created_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            stat = file_path.stat()
            created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        explicit_title = None
        metadata = self._get_session_metadata(session_id, project_dir)
        if metadata and metadata.get("summary"):
            explicit_title = metadata["summary"]

        message_title = self._extract_title_from_records(scan.head_records[:20])
        directory_title = basename_title(first_line.get("cwd")) or basename_title(project_dir)
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
                "project": project_dir.name,
                "cwd": first_line.get("cwd", ""),
                "version": first_line.get("version", ""),
                "model": model,
                "message_count": message_count,
            },
        )

    def get_session_uri(self, session: Session) -> str:
        """Get the agent session URI for a session - Claude uses 'claude://' scheme"""
        return f"claude://{session.id}"

    def _extract_title(self, lines: list[str]) -> str | None:
        """Extract title from user messages"""
        try:
            return self._extract_title_from_records(parse_object_lines(lines[:20]))
        except Exception as e:
            self._report_diagnostic(Keys.WARN_TITLE_EXTRACT_FAILED, error=str(e))

        return None

    def _extract_title_from_records(self, records: list[dict[str, Any]]) -> str | None:
        for data in records:
            msg = data.get("message", {})
            if not isinstance(msg, dict):
                continue

            if msg.get("role") != "user":
                continue

            content = msg.get("content", "")
            if not content:
                continue
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        texts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        texts.append(item)
                content = " ".join(texts)
            return normalize_title_text(content)

        return None

    def get_session_data(self, session: Session) -> dict[str, Any]:
        """Get session data as a dictionary"""
        if not session.source_path.exists():
            raise source_missing(
                "session source file is missing",
                missing_path=session.source_path,
                searched_roots=[root.render() for root in self.get_search_roots()],
                next_steps=(
                    i18n.t(Keys.DIAG_STEP_CLAUDE_SESSION_LOCATION),
                    i18n.t(Keys.DIAG_STEP_LIST_TO_CHECK_EXISTS),
                ),
            )

        decoder = ClaudeTranscriptDecoder()

        scan = JsonlObjectScan(session.source_path)
        for data in scan:
            try:
                decoder.append_record(data)
            except Exception as e:
                self._report_diagnostic(Keys.WARN_MESSAGE_CONVERT_FAILED, error=str(e))
                continue
        if diagnostic := skipped_records_diagnostic(scan):
            self._report_diagnostic(diagnostic.message_key, **diagnostic.fields)

        input_tokens, output_tokens = decoder.token_totals()
        stats: NormalizedSessionStats = {
            "total_cost": 0,
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "message_count": len(decoder.messages),
        }

        session_data: NormalizedSessionData = {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": session.metadata.get("cwd", ""),
            "version": session.metadata.get("version", ""),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": decoder.messages,
        }
        return dict(session_data)
