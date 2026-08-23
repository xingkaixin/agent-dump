"""Shared scan machinery for providers whose sessions are discovered by scanning files."""

from abc import abstractmethod
from collections.abc import Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextvars import Context, copy_context
from datetime import datetime, timedelta, timezone
from itertools import chain, islice
from pathlib import Path

from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.agents.jsonl_scan import file_modified_since
from agent_dump.i18n import Keys
from agent_dump.paths import first_existing_search_root
from agent_dump.time_utils import normalize_datetime_utc

_MAX_SCAN_WORKERS = 32


class FileSessionAgent(BaseAgent):
    """Base for providers whose sessions live as files under one root directory.

    Subclasses implement `_iter_session_files` and `_parse_session_file`;
    availability probing, mtime pruning, parallel parsing, cutoff filtering,
    sorting, and filename-based lookup are shared here.
    """

    def __init__(self, name: str | None = None, display_name: str | None = None) -> None:
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

    def _report_parse_failure(self, file_path: Path, exc: Exception) -> None:
        self._report_diagnostic(Keys.WARN_SESSION_PARSE_FAILED, path=str(file_path), error=str(exc))

    def _should_scan_file_or_report(self, file_path: Path, cutoff: datetime) -> bool:
        try:
            return self._should_scan_file(file_path, cutoff)
        except Exception as exc:
            self._report_parse_failure(file_path, exc)
            return False

    def _parse_session_file_or_report(self, file_path: Path) -> Session | None:
        try:
            return self._parse_session_file(file_path)
        except Exception as exc:
            self._report_parse_failure(file_path, exc)
            return None

    def _find_base_path(self) -> Path | None:
        return first_existing_search_root(*self.get_search_roots())

    def _ensure_base_path(self) -> Path | None:
        if self.base_path is not None:
            return self.base_path
        self.base_path = self._find_base_path()
        return self.base_path

    def is_available(self) -> bool:
        if not self._ensure_base_path():
            return False
        return next(iter(self._iter_session_files()), None) is not None

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        """Get sessions from the requested time window."""
        return list(self.discover_sessions(days).sessions)

    def _iter_parsed_sessions(self, session_files: Iterable[Path]) -> Iterator[Session | None]:
        file_iterator = iter(session_files)
        initial_files = tuple(islice(file_iterator, _MAX_SCAN_WORKERS))
        if not initial_files:
            return

        def parse_in_context(context: Context, path: Path) -> Session | None:
            return context.run(self._parse_session_file_or_report, path)

        with ThreadPoolExecutor(max_workers=len(initial_files)) as executor:
            pending: set[Future[Session | None]] = {
                executor.submit(parse_in_context, copy_context(), path) for path in initial_files
            }
            while pending:
                completed, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    yield future.result()
                    next_path = next(file_iterator, None)
                    if next_path is not None:
                        pending.add(executor.submit(parse_in_context, copy_context(), next_path))

    def discover_sessions(self, days: int | None = 7) -> ProviderDiscovery:
        """Discover candidate files once for availability and windowed parsing."""
        if not self._ensure_base_path():
            return ProviderDiscovery(available=False)

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days) if days is not None else None
        file_iterator = iter(self._iter_session_files())
        first_file = next(file_iterator, None)
        if first_file is None:
            return ProviderDiscovery(available=False)
        session_files: Iterable[Path] = chain((first_file,), file_iterator)
        if cutoff_time is not None:
            session_files = (
                file_path for file_path in session_files if self._should_scan_file_or_report(file_path, cutoff_time)
            )

        sessions: list[Session] = []
        for session in self._iter_parsed_sessions(session_files):
            if session and (cutoff_time is None or normalize_datetime_utc(session.created_at) >= cutoff_time):
                sessions.append(session)

        ordered_sessions = sorted(sessions, key=lambda s: normalize_datetime_utc(s.created_at), reverse=True)
        return ProviderDiscovery(available=True, sessions=tuple(ordered_sessions))

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Try filename-based candidates before falling back to a full scan."""
        if base_path := self._ensure_base_path():
            resolved_base_path = base_path.resolve()
            for file_path in self._session_file_candidates(session_id):
                try:
                    candidate_path = file_path.resolve()
                except (OSError, RuntimeError):
                    continue
                if not candidate_path.is_relative_to(resolved_base_path):
                    continue
                session = self._parse_session_file_or_report(file_path)
                if session is not None and session.id == session_id:
                    return session
        return super().find_session_by_id(session_id)
