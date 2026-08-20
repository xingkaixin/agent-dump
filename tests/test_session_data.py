"""Tests for bounded request-scoped session data caching."""

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gc
from pathlib import Path
import threading
import time
import tracemalloc
from typing import Any

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.session_data import SessionDataCache


class DataAgent(BaseAgent):
    def __init__(self, loader: Callable[[Session], dict[str, Any]]) -> None:
        super().__init__(name="test", display_name="Test")
        self._loader = loader
        self.reads: Counter[str] = Counter()
        self._reads_lock = threading.Lock()

    def scan(self) -> list[Session]:
        return []

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        return []

    def get_session_data(self, session: Session) -> dict[str, Any]:
        with self._reads_lock:
            self.reads[session.id] += 1
        return self._loader(session)


def make_session(session_id: str) -> Session:
    timestamp = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return Session(
        id=session_id,
        title=session_id,
        created_at=timestamp,
        updated_at=timestamp,
        source_path=Path(f"/missing/{session_id}.jsonl"),
        metadata={},
    )


def wait_for_lease_count(cache: SessionDataCache, expected: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with cache._lock:
            counts = [entry.lease_count for entry in cache._entries.values()]
        if counts == [expected]:
            return
        time.sleep(0.001)
    raise AssertionError(f"lease count did not reach {expected}: {counts}")


def test_rejects_negative_completed_entry_limit() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        SessionDataCache(completed_entry_limit=-1)


def test_completed_entries_follow_lru_limit() -> None:
    cache = SessionDataCache(completed_entry_limit=2)
    agent = DataAgent(lambda session: {"session_id": session.id})
    first, second, third = (make_session(session_id) for session_id in ("first", "second", "third"))

    cache.get(agent, first)
    cache.get(agent, second)
    cache.get(agent, first)
    cache.get(agent, third)
    cache.get(agent, first)
    cache.get(agent, second)

    assert agent.reads == Counter({"second": 2, "first": 1, "third": 1})
    assert len(cache._entries) == 2


def test_concurrent_leases_coalesce_and_release_after_last_consumer() -> None:
    cache = SessionDataCache()
    session = make_session("shared")
    load_started = threading.Event()
    release_load = threading.Event()
    payload = {"messages": []}

    def load(_session: Session) -> dict[str, Any]:
        load_started.set()
        if not release_load.wait(timeout=5):
            raise AssertionError("session load was not released")
        return payload

    agent = DataAgent(load)

    def read() -> dict[str, Any]:
        with cache.lease(agent, session) as data:
            return data

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(read) for _ in range(4)]
        assert load_started.wait(timeout=5)
        wait_for_lease_count(cache, 4)
        release_load.set()
        results = [future.result() for future in futures]

    assert agent.reads == Counter({"shared": 1})
    assert all(result is payload for result in results)
    assert not cache._entries


def test_in_flight_entry_is_not_evicted_or_loaded_twice() -> None:
    cache = SessionDataCache(completed_entry_limit=1)
    slow = make_session("slow")
    load_started = threading.Event()
    release_load = threading.Event()
    payload = {"session_id": "slow"}

    def load(session: Session) -> dict[str, Any]:
        if session.id == "slow":
            load_started.set()
            if not release_load.wait(timeout=5):
                raise AssertionError("slow load was not released")
            return payload
        return {"session_id": session.id}

    agent = DataAgent(load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get, agent, slow)
        assert load_started.wait(timeout=5)
        cache.get(agent, make_session("fast-1"))
        cache.get(agent, make_session("fast-2"))
        second = executor.submit(cache.get, agent, slow)
        release_load.set()

        assert first.result() is payload
        assert second.result() is payload

    assert agent.reads["slow"] == 1
    assert len(cache._entries) == 1


def test_changed_signal_replaces_completed_entry() -> None:
    cache = SessionDataCache(completed_entry_limit=4)
    session = make_session("changed")
    agent = DataAgent(lambda _session: {"generation": sum(agent.reads.values())})

    first = cache.get(agent, session)
    session.updated_at += timedelta(seconds=1)
    second = cache.get(agent, session)

    assert first == {"generation": 1}
    assert second == {"generation": 2}
    assert len(cache._entries) == 1


def test_changed_signal_waits_for_old_in_flight_read_before_replacing_it() -> None:
    cache = SessionDataCache(completed_entry_limit=4)
    session = make_session("changing")
    first_started = threading.Event()
    release_first = threading.Event()

    def load(_session: Session) -> dict[str, Any]:
        generation = sum(agent.reads.values())
        if generation == 1:
            first_started.set()
            if not release_first.wait(timeout=5):
                raise AssertionError("first generation was not released")
        return {"generation": generation}

    agent = DataAgent(load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        old_read = executor.submit(cache.get, agent, session)
        assert first_started.wait(timeout=5)
        session.updated_at += timedelta(seconds=1)
        new_read = executor.submit(cache.get, agent, session)
        release_first.set()

        assert old_read.result() == {"generation": 1}
        assert new_read.result() == {"generation": 2}

    assert agent.reads == Counter({"changing": 2})
    assert len(cache._entries) == 1


def test_failed_lease_does_not_pollute_cache_and_can_retry() -> None:
    cache = SessionDataCache()
    session = make_session("retry")
    expected = {"messages": []}

    def load(_session: Session) -> dict[str, Any]:
        if agent.reads["retry"] == 1:
            raise ValueError("temporary failure")
        return expected

    agent = DataAgent(load)

    with pytest.raises(ValueError, match="temporary failure"), cache.lease(agent, session):
        pass
    with cache.lease(agent, session) as result:
        assert result is expected

    assert agent.reads == Counter({"retry": 2})
    assert not cache._entries


def test_transient_leases_bound_full_payload_memory() -> None:
    cache = SessionDataCache()
    payload_size = 256 * 1024
    sessions = [make_session(f"session-{index}") for index in range(100)]
    agent = DataAgent(lambda _session: {"blob": bytearray(payload_size)})

    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    for session in sessions:
        with cache.lease(agent, session) as data:
            assert len(data["blob"]) == payload_size
        del data
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert sum(agent.reads.values()) == len(sessions)
    assert not cache._entries
    assert current - baseline < payload_size * 2
    assert peak - baseline < payload_size * 8
