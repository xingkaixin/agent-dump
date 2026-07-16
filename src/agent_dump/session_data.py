"""Request-scoped session data loading helpers."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from agent_dump.time_utils import normalize_datetime_utc

if TYPE_CHECKING:
    from agent_dump.agents.base import BaseAgent, Session


def session_updated_signal(session: Session) -> float:
    """Return a change signal for one session without using shared database mtimes."""
    signals = [normalize_datetime_utc(session.updated_at).timestamp()]
    signals.extend(_path_mtime(path) for path in extract_related_source_paths(session))
    return max(signals)


def extract_related_source_paths(session: Session) -> tuple[Path, ...]:
    """Return per-session files that can invalidate parsed data."""
    related_paths: list[Path] = []
    for key in ("context_file", "wire_file"):
        raw_path = session.metadata.get(key)
        if isinstance(raw_path, str) and raw_path.strip():
            related_paths.append(Path(raw_path))
    return tuple(dict.fromkeys(related_paths))


def _path_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    return path.stat().st_mtime


class SessionDataCache:
    """Coalesce parsed session reads for the lifetime of one agent instance."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, float], Future[dict[str, Any]]] = {}
        self._lock = Lock()

    def get(self, agent: BaseAgent, session: Session) -> dict[str, Any]:
        """Return parsed data, reloading when the session change signal differs."""
        key = (agent.name, session.id, session_updated_signal(session))
        with self._lock:
            future = self._entries.get(key)
            should_load = future is None
            if future is None:
                future = Future()
                self._entries[key] = future

        if should_load:
            try:
                future.set_result(agent.get_session_data(session))
            except BaseException as exc:
                future.set_exception(exc)
                with self._lock:
                    self._entries.pop(key, None)

        return future.result()
