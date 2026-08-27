"""Concurrent index writers must not wait for unrelated provider reads."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from threading import Event
from typing import Any
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.search_index import SearchIndex


class TextAgent(BaseAgent):
    def __init__(self, text: str) -> None:
        super().__init__("codex", "Codex")
        self.text = text

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        return []

    def get_session_data(self, session: Session) -> dict[str, Any]:
        return {"messages": [{"role": "user", "content": self.text}]}


def make_session(root: Path, session_id: str, revision: int = 0) -> Session:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Session(session_id, "task", created_at, created_at + timedelta(seconds=revision), root / session_id, {})


@pytest.mark.parametrize("later_batch", [False, True])
def test_other_update_completes_while_provider_read_is_paused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later_batch: bool
) -> None:
    monkeypatch.setattr("agent_dump.search_index._INDEX_BATCH_SIZE", 1)
    database = tmp_path / "index.db"
    index = SearchIndex(database)
    index.ensure_initialized()
    agent = TextAgent("slowbody")
    started, release = Event(), Event()
    sessions = [make_session(tmp_path, "slow")]
    if later_batch:
        sessions.insert(0, make_session(tmp_path, "first"))
    read = agent.get_session_data

    def paused_read(session: Session) -> dict[str, Any]:
        if session.id == "slow":
            started.set()
            assert release.wait(timeout=10)
        return read(session)

    with mock.patch.object(agent, "get_session_data", side_effect=paused_read), ThreadPoolExecutor(2) as executor:
        slow = executor.submit(index.update, agent, sessions)
        try:
            assert started.wait(timeout=5)
            fast = executor.submit(
                SearchIndex(database).update, TextAgent("fastbody"), [make_session(tmp_path, "fast")]
            )
            assert fast.result(timeout=3) == (1, 0)
        finally:
            release.set()
        assert slow.result(timeout=5) == (len(sessions), 0)

    assert len(index.search("slowbody")) == len(sessions)
    assert [result.session_id for result in index.search("fastbody")] == ["fast"]


@pytest.mark.parametrize("seeded", [False, True])
@pytest.mark.parametrize("slow_fails", [False, True])
def test_slow_read_does_not_replace_or_delete_a_concurrent_refresh(
    tmp_path: Path, seeded: bool, slow_fails: bool
) -> None:
    database = tmp_path / "index.db"
    index = SearchIndex(database)
    index.ensure_initialized()
    if seeded:
        index.update(TextAgent("initialbody"), [make_session(tmp_path, "shared")])
    agent = TextAgent("stalebody")
    started, release = Event(), Event()
    read = agent.get_session_data

    def paused_read(session: Session) -> dict[str, Any]:
        started.set()
        assert release.wait(timeout=10)
        if slow_fails:
            raise OSError("provider read failed")
        return read(session)

    with mock.patch.object(agent, "get_session_data", side_effect=paused_read), ThreadPoolExecutor(2) as executor:
        slow = executor.submit(index.update, agent, [make_session(tmp_path, "shared", 1)])
        try:
            assert started.wait(timeout=5)
            fast = executor.submit(
                SearchIndex(database).update, TextAgent("freshbody"), [make_session(tmp_path, "shared", 2)]
            )
            assert fast.result(timeout=3) == (1, 0)
        finally:
            release.set()
        assert slow.result(timeout=5) == (0, 0)

    assert [result.session_id for result in index.search("freshbody")] == ["shared"]
    assert index.search("stalebody") == []
    with closing(sqlite3.connect(database)) as connection:
        expected = {row[0] for row in connection.execute("SELECT fts_rowid FROM index_state")}
        assert len(expected) == 1
        for table in ("sessions_fts", "sessions_fts_trigram"):
            assert {row[0] for row in connection.execute(f"SELECT rowid FROM {table}")} == expected


def test_later_observation_survives_a_slow_refresh(tmp_path: Path) -> None:
    database = tmp_path / "index.db"
    index = SearchIndex(database)
    original = make_session(tmp_path, "shared")
    index.update(TextAgent("initialbody"), [original])
    later_observations: list[float] = []
    agent = TextAgent("freshbody")
    read = agent.get_session_data

    def observe_then_read(session: Session) -> dict[str, Any]:
        assert SearchIndex(database).update(TextAgent("unused"), [original]) == (0, 0)
        with closing(sqlite3.connect(database)) as connection:
            later_observations.append(connection.execute("SELECT last_seen_at FROM index_state").fetchone()[0])
        return read(session)

    with mock.patch.object(agent, "get_session_data", side_effect=observe_then_read):
        assert index.update(agent, [make_session(tmp_path, "shared", 1)]) == (1, 0)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT last_seen_at FROM index_state").fetchone()[0] >= later_observations[0]
    assert len(index.search("freshbody")) == 1


@pytest.mark.parametrize("seeded", [False, True])
@pytest.mark.parametrize(
    ("new_revision", "new_text", "expected_added", "expected_body"),
    [(2, "newbody", 1, "newbody"), (2, None, 0, None), (1, "oldbody", 0, "oldbody"), (1, None, 0, "oldbody")],
)
def test_later_observation_handles_an_earlier_write_that_finishes_first(
    tmp_path: Path,
    seeded: bool,
    new_revision: int,
    new_text: str | None,
    expected_added: int,
    expected_body: str | None,
) -> None:
    database = tmp_path / "index.db"
    index = SearchIndex(database)
    index.ensure_initialized()
    if seeded:
        index.update(TextAgent("initialbody"), [make_session(tmp_path, "shared")])
    old_agent, new_agent = TextAgent("oldbody"), TextAgent(new_text or "")
    old_started, new_started = Event(), Event()
    release_old, release_new = Event(), Event()
    old_read, new_read = old_agent.get_session_data, new_agent.get_session_data

    def read_old(session: Session) -> dict[str, Any]:
        old_started.set()
        assert release_old.wait(timeout=10)
        return old_read(session)

    def read_new(session: Session) -> dict[str, Any]:
        new_started.set()
        assert release_new.wait(timeout=10)
        if new_text is None:
            raise OSError("provider read failed")
        return new_read(session)

    with (
        mock.patch.object(old_agent, "get_session_data", side_effect=read_old),
        mock.patch.object(new_agent, "get_session_data", side_effect=read_new),
        ThreadPoolExecutor(2) as executor,
    ):
        old = executor.submit(index.update, old_agent, [make_session(tmp_path, "shared", 1)])
        try:
            assert old_started.wait(timeout=5)
            new = executor.submit(
                SearchIndex(database).update, new_agent, [make_session(tmp_path, "shared", new_revision)]
            )
            assert new_started.wait(timeout=5)
            release_old.set()
            assert old.result(timeout=5) == (1, 0)
        finally:
            release_old.set()
            release_new.set()
        assert new.result(timeout=5) == (expected_added, 0)

    for body in ("oldbody", "newbody"):
        assert len(index.search(body)) == int(body == expected_body)


def test_slow_read_does_not_restore_a_concurrently_removed_row(tmp_path: Path) -> None:
    database = tmp_path / "index.db"
    index = SearchIndex(database)
    index.update(TextAgent("initialbody"), [make_session(tmp_path, "shared")])
    agent = TextAgent("stalebody")
    read = agent.get_session_data

    def remove_then_read(session: Session) -> dict[str, Any]:
        assert SearchIndex(database).clear_agent(agent.name) == 1
        return read(session)

    with mock.patch.object(agent, "get_session_data", side_effect=remove_then_read):
        assert index.update(agent, [make_session(tmp_path, "shared", 1)]) == (0, 0)

    assert index.get_stats() == {}
    assert index.search("initialbody") == []
    assert index.search("stalebody") == []


def test_failed_batch_rolls_back_both_fts_tables_and_index_state(tmp_path: Path) -> None:
    database = tmp_path / "index.db"
    index = SearchIndex(database)
    index.ensure_initialized()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TRIGGER reject_bad BEFORE INSERT ON index_state "
            "WHEN NEW.session_id = 'bad' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        index.update(TextAgent("body"), [make_session(tmp_path, "good"), make_session(tmp_path, "bad")])

    with closing(sqlite3.connect(database)) as connection:
        for table in ("index_state", "sessions_fts", "sessions_fts_trigram"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
