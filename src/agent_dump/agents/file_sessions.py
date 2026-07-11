"""Shared scan machinery for providers whose sessions are discovered by scanning files."""

from abc import abstractmethod
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.agents.jsonl_scan import file_modified_since
from agent_dump.paths import first_existing_search_root
from agent_dump.time_utils import normalize_datetime_utc

_MAX_SCAN_WORKERS = 32


class FileSessionAgent(BaseAgent):
    """Base for providers whose sessions live as files under one root directory.

    Subclasses implement `_iter_session_files` and `_parse_session_file`;
    availability probing, mtime pruning, parallel parsing, cutoff filtering,
    sorting, and filename-based lookup are shared here.
    """

    def __init__(self, name: str, display_name: str):
        super().__init__(name, display_name)
        self.base_path: Path | None = None

    @abstractmethod
    def _iter_session_files(self) -> Iterator[Path]:
        """Yield every candidate session file. Only called with base_path set."""

    @abstractmethod
    def _parse_session_file(self, file_path: Path) -> Session | None:
        """Parse one session file; return None when it holds no session."""

    def _session_file_candidates(self, session_id: str) -> Iterable[Path]:
        """Files likely to contain the session, for the find_session_by_id fast path."""
        del session_id
        return ()

    def _should_scan_file(self, file_path: Path, cutoff: datetime) -> bool:
        """Whether a file may contain sessions inside the window; default prunes by mtime."""
        return file_modified_since(file_path, cutoff)

    def _find_base_path(self) -> Path | None:
        return first_existing_search_root(*self.get_search_roots())

    def is_available(self) -> bool:
        self.base_path = self._find_base_path()
        if not self.base_path:
            return False
        return next(iter(self._iter_session_files()), None) is not None

    def scan(self) -> list[Session]:
        """Scan for all available sessions."""
        if not self.is_available():
            return []
        return self.get_sessions(days=3650)

    def get_sessions(self, days: int = 7) -> list[Session]:
        """Get sessions from the last N days."""
        if not self.base_path:
            return []

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        session_files = [
            file_path for file_path in self._iter_session_files() if self._should_scan_file(file_path, cutoff_time)
        ]
        if not session_files:
            return []

        sessions: list[Session] = []
        max_workers = min(_MAX_SCAN_WORKERS, len(session_files))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._parse_session_file, path): path for path in session_files}
            for future in as_completed(futures):
                path = futures[future]
                try:
                    session = future.result()
                except Exception as e:
                    print(f"警告: 解析会话文件失败 {path}: {e}", file=sys.stderr)
                    continue
                if session and normalize_datetime_utc(session.created_at) >= cutoff_time:
                    sessions.append(session)

        return sorted(sessions, key=lambda s: normalize_datetime_utc(s.created_at), reverse=True)

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Try filename-based candidates before falling back to a full scan."""
        if self.base_path:
            for file_path in self._session_file_candidates(session_id):
                session = self._parse_session_file(file_path)
                if session is not None and session.id == session_id:
                    return session
        return super().find_session_by_id(session_id)
