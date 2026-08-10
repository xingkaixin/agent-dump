"""Request-scoped session data loading helpers."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from concurrent.futures import Future, wait
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from agent_dump.time_utils import normalize_datetime_utc

if TYPE_CHECKING:
    from agent_dump.agents.base import BaseAgent, Session

MAX_COMPLETED_SESSION_DATA_ENTRIES = 32
_SessionIdentity = tuple[str, str]


@dataclass
class _CacheEntry:
    signal: float
    future: Future[dict[str, Any]]
    lease_count: int = 0
    retain_after_use: bool = False


def session_updated_signal(agent: BaseAgent, session: Session) -> float:
    """Return a change signal for one session without using shared database mtimes."""
    signals = [normalize_datetime_utc(session.updated_at).timestamp()]
    facts = agent.get_session_facts(session)
    signals.extend(_path_mtime(path) for path in facts.change_sources)
    return max(signals)


def _path_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    return path.stat().st_mtime


class SessionDataCache:
    """Coalesce active reads and retain a bounded set of completed payloads."""

    def __init__(self, *, completed_entry_limit: int = MAX_COMPLETED_SESSION_DATA_ENTRIES) -> None:
        if completed_entry_limit < 0:
            raise ValueError("completed entry limit cannot be negative")
        self._completed_entry_limit = completed_entry_limit
        self._entries: OrderedDict[_SessionIdentity, _CacheEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, agent: BaseAgent, session: Session) -> dict[str, Any]:
        """Return parsed data, reloading when the session change signal differs."""
        data, _, _ = self._acquire(agent, session, retain_after_use=True)
        return data

    @contextmanager
    def lease(self, agent: BaseAgent, session: Session) -> Iterator[dict[str, Any]]:
        """Yield parsed data and release this lease's completed entry on exit."""
        data, identity, entry = self._acquire(agent, session, retain_after_use=False)
        try:
            yield data
        finally:
            self._release_lease(identity, entry)

    def _acquire(
        self,
        agent: BaseAgent,
        session: Session,
        *,
        retain_after_use: bool,
    ) -> tuple[dict[str, Any], _SessionIdentity, _CacheEntry]:
        identity = (agent.name, session.id)
        while True:
            signal = session_updated_signal(agent, session)
            stale_future: Future[dict[str, Any]] | None = None
            future: Future[dict[str, Any]] | None = None
            entry: _CacheEntry | None = None
            should_load = False
            with self._lock:
                existing = self._entries.get(identity)
                if existing is not None and existing.signal != signal and not existing.future.done():
                    stale_future = existing.future
                else:
                    should_load = existing is None or existing.signal != signal
                    if should_load:
                        entry = _CacheEntry(signal=signal, future=Future())
                        self._entries[identity] = entry
                    else:
                        if existing is None:
                            raise AssertionError("cache entry selection lost the existing entry")
                        entry = existing
                    self._entries.move_to_end(identity)
                    if retain_after_use:
                        entry.retain_after_use = True
                    else:
                        entry.lease_count += 1
                    future = entry.future

            if stale_future is not None:
                wait((stale_future,))
                continue
            if entry is None or future is None:
                raise AssertionError("cache entry selection produced no active entry")

            if should_load:
                self._load_entry(agent, session, identity, entry)

            try:
                return future.result(), identity, entry
            except BaseException:
                if not retain_after_use:
                    self._decrement_lease(entry)
                raise

    def _load_entry(
        self,
        agent: BaseAgent,
        session: Session,
        identity: _SessionIdentity,
        entry: _CacheEntry,
    ) -> None:
        try:
            entry.future.set_result(agent.get_session_data(session))
        except BaseException as exc:
            entry.future.set_exception(exc)
            with self._lock:
                if self._entries.get(identity) is entry:
                    self._entries.pop(identity)
            return

        with self._lock:
            if self._entries.get(identity) is entry:
                self._entries.move_to_end(identity)
                self._evict_completed_entries()

    def _release_lease(self, identity: _SessionIdentity, entry: _CacheEntry) -> None:
        with self._lock:
            self._decrement_lease(entry)
            if self._entries.get(identity) is not entry:
                return
            if entry.lease_count == 0 and not entry.retain_after_use:
                self._entries.pop(identity)
            else:
                self._evict_completed_entries()

    @staticmethod
    def _decrement_lease(entry: _CacheEntry) -> None:
        if entry.lease_count > 0:
            entry.lease_count -= 1

    def _evict_completed_entries(self) -> None:
        completed_count = sum(entry.future.done() and entry.lease_count == 0 for entry in self._entries.values())
        while completed_count > self._completed_entry_limit:
            identity = next(
                identity for identity, entry in self._entries.items() if entry.future.done() and entry.lease_count == 0
            )
            self._entries.pop(identity)
            completed_count -= 1
