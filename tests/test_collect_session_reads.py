"""Collect session reading, concurrency, and failure isolation tests."""

from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor, wait as wait_for_futures
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
from unittest import mock

from collect_test_support import configure_session_data_lease
from locale_helpers import Keys, expect
import pytest

from agent_dump.agents.base import Session, derive_session_facts
from agent_dump.collect_logging import CollectLogger
from agent_dump.collect_models import (
    CollectEntry,
    CollectProgressEvent,
    ScanSessionsProgress,
)
import agent_dump.collect_sessions as collect_sessions_module
from agent_dump.collect_sessions import collect_entries
from agent_dump.config import CollectConfig


class TestCollectEntries:
    def test_collect_entries_filters_and_extracts(self):
        now = datetime.now(timezone.utc)
        in_range = mock.MagicMock()
        in_range.id = "s-in"
        in_range.title = "in"
        in_range.created_at = now - timedelta(days=1)
        in_range.updated_at = now - timedelta(days=1)
        in_range.metadata = {"cwd": "/repo/a"}

        out_range = mock.MagicMock()
        out_range.id = "s-out"
        out_range.title = "out"
        out_range.created_at = now - timedelta(days=40)
        out_range.updated_at = now - timedelta(days=40)
        out_range.metadata = {"cwd": "/repo/b"}

        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [in_range, out_range]
        agent.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "修复 /repo/a.py 报错"}]}]
        }
        configure_session_data_lease(agent)

        progress: list[CollectProgressEvent] = []
        entries = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=(now - timedelta(days=2)).date(),
            until_date=now.date(),
            progress_callback=progress.append,
        )

        assert len(entries) == 1
        assert entries[0].session_id == "s-in"
        assert entries[0].project_directory == "/repo/a"
        assert entries[0].events[0].kind == "user_message"
        assert entries[0].is_truncated is False
        assert [event.stage for event in progress] == ["scan_sessions", "scan_sessions"]
        assert isinstance(progress[-1], ScanSessionsProgress)
        assert progress[-1].current == 1
        assert progress[-1].total == 1

    def test_collect_entries_ignores_sessions_without_visible_dialogue(self):
        now = datetime.now(timezone.utc)
        empty_session = Session("empty", "empty", now, now, Path("/tmp/empty.jsonl"), {})
        visible_session = Session("visible", "visible", now, now, Path("/tmp/visible.jsonl"), {})
        session_data = {
            "empty": {
                "messages": [
                    {"role": "assistant", "parts": [{"type": "reasoning", "text": "internal"}]},
                    {"role": "assistant", "parts": [{"type": "tool", "tool": "exec_command", "state": {}}]},
                ]
            },
            "visible": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "修复问题"}]}]},
        }
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [empty_session, visible_session]
        agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
        agent.get_cached_session_data.side_effect = lambda session: session_data[session.id]
        configure_session_data_lease(agent)

        entries = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=now.date(),
            until_date=now.date(),
            local_tz=timezone.utc,
        )

        assert [entry.session_id for entry in entries] == ["visible"]

    def test_collect_entry_uses_provider_session_facts_for_project_directory(self):
        now = datetime.now(timezone.utc)
        session = Session(
            id="s-provider-facts",
            title="provider facts",
            created_at=now,
            updated_at=now,
            source_path=Path("/tmp/s-provider-facts.jsonl"),
            metadata={"cwd": "/stale/project"},
        )
        facts_session = Session(
            id="facts",
            title="facts",
            created_at=now,
            updated_at=now,
            source_path=session.source_path,
            metadata={"cwd": "/provider/project"},
        )
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [session]
        agent.get_session_uri.return_value = "codex://s-provider-facts"
        agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "work"}]}]
        }
        configure_session_data_lease(agent)
        agent.get_session_facts.side_effect = None
        agent.get_session_facts.return_value = derive_session_facts(facts_session)

        entries = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=now.date(),
            until_date=now.date(),
            local_tz=timezone.utc,
        )

        assert entries[0].project_directory == "/provider/project"
        agent.get_session_facts.assert_called_with(session)

    def test_collect_deny_uses_provider_session_facts(self):
        now = datetime.now(timezone.utc)
        session = Session(
            id="s-denied-facts",
            title="denied facts",
            created_at=now,
            updated_at=now,
            source_path=Path("/tmp/s-denied-facts.jsonl"),
            metadata={"cwd": "/metadata/allows"},
        )
        facts_session = Session(
            id="facts",
            title="facts",
            created_at=now,
            updated_at=now,
            source_path=session.source_path,
            metadata={"cwd": "/provider/denied"},
        )
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [session]
        configure_session_data_lease(agent)
        agent.get_session_facts.side_effect = None
        agent.get_session_facts.return_value = derive_session_facts(facts_session)

        entries = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=now.date(),
            until_date=now.date(),
            collect_config=CollectConfig(agent_denies={"codex": ("/provider/denied",)}),
            local_tz=timezone.utc,
        )

        assert entries == []
        agent.get_session_facts.assert_called_once_with(session)

    def test_collect_normalizes_each_configured_deny_path_once(self, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        sessions = [
            Session(
                id=f"session-{index}",
                title=f"session {index}",
                created_at=now - timedelta(days=40),
                updated_at=now - timedelta(days=40),
                source_path=Path(f"/tmp/session-{index}.jsonl"),
                metadata={"cwd": f"/allowed/project-{index}"},
            )
            for index in range(2)
        ]
        agent = mock.MagicMock()
        agent.name = "codex"
        configure_session_data_lease(agent)

        normalized_values: list[str] = []
        normalize_path = collect_sessions_module._normalize_collect_project_path

        def record_normalization(value: str) -> Path | None:
            normalized_values.append(value)
            return normalize_path(value)

        monkeypatch.setattr(collect_sessions_module, "_normalize_collect_project_path", record_normalization)

        entries = collect_entries(
            session_groups=[(agent, sessions)],
            since_date=now.date(),
            until_date=now.date(),
            collect_config=CollectConfig(agent_denies={"codex": ("/blocked/one", "/blocked/two")}),
            local_tz=timezone.utc,
        )

        assert entries == []
        assert normalized_values.count("/blocked/one") == 1
        assert normalized_values.count("/blocked/two") == 1

    def test_collect_entries_parses_concurrently_and_preserves_order(self) -> None:
        now = datetime.now(timezone.utc)
        newer = Session(
            id="newer",
            title="newer",
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
            source_path=Path("/tmp/newer.jsonl"),
            metadata={"cwd": "/repo/newer"},
        )
        older = Session(
            id="older",
            title="older",
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            source_path=Path("/tmp/older.jsonl"),
            metadata={"cwd": "/repo/older"},
        )
        release_reads = threading.Event()
        read_lock = threading.Lock()
        started_sessions: set[str] = set()
        worker_threads: set[int] = set()

        def get_session_data(session: Session) -> dict[str, object]:
            with read_lock:
                started_sessions.add(session.id)
                worker_threads.add(threading.get_ident())
                if len(started_sessions) == 2:
                    release_reads.set()
            if not release_reads.wait(timeout=5):
                raise AssertionError("session reads did not overlap")
            return {"messages": [{"role": "user", "content": f"work on {session.id}"}]}

        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [newer, older]
        agent.get_cached_session_data.side_effect = get_session_data
        agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
        configure_session_data_lease(agent)
        progress: list[CollectProgressEvent] = []

        entries = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            local_tz=timezone.utc,
            progress_callback=progress.append,
        )

        assert len(worker_threads) == 2
        assert [entry.session_id for entry in entries] == ["older", "newer"]
        scan_events = [event for event in progress if isinstance(event, ScanSessionsProgress)]
        assert [event.session_uri for event in scan_events[1:]] == ["codex://newer", "codex://older"]

    def test_collect_entries_bounds_submitted_session_reads(self, monkeypatch) -> None:
        now = datetime.now(timezone.utc)
        sessions = [
            Session(
                id=f"session-{index}",
                title=f"session-{index}",
                created_at=now - timedelta(minutes=index),
                updated_at=now - timedelta(minutes=index),
                source_path=Path(f"/tmp/session-{index}.jsonl"),
                metadata={},
            )
            for index in range(5)
        ]
        release_reads = threading.Event()
        wait_called = threading.Event()
        submitted_sessions: list[str] = []

        class RecordingThreadPoolExecutor(RealThreadPoolExecutor):
            def submit(self, function, /, *args, **kwargs):
                submitted_sessions.append(args[0][1].id)
                return super().submit(function, *args, **kwargs)

        def recording_wait(*args, **kwargs):
            wait_called.set()
            return wait_for_futures(*args, **kwargs)

        def get_session_data(session: Session) -> dict[str, object]:
            if not release_reads.wait(timeout=5):
                raise AssertionError(f"session read did not resume: {session.id}")
            return {"messages": [{"role": "user", "content": session.id}]}

        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = sessions
        agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
        agent.get_cached_session_data.side_effect = get_session_data
        configure_session_data_lease(agent)
        monkeypatch.setattr("agent_dump.collect_sessions._MAX_SESSION_PARSE_WORKERS", 2)
        monkeypatch.setattr("agent_dump.collect_sessions.ThreadPoolExecutor", RecordingThreadPoolExecutor)
        monkeypatch.setattr("agent_dump.bounded_concurrency.wait", recording_wait)
        results: list[list[CollectEntry]] = []
        collector = threading.Thread(
            target=lambda: results.append(
                collect_entries(
                    session_groups=[(agent, agent.get_sessions.return_value)],
                    since_date=(now - timedelta(days=1)).date(),
                    until_date=now.date(),
                    local_tz=timezone.utc,
                )
            )
        )

        collector.start()
        assert wait_called.wait(timeout=5)
        assert submitted_sessions == ["session-0", "session-1"]
        release_reads.set()
        collector.join(timeout=5)

        assert not collector.is_alive()
        assert len(submitted_sessions) == len(sessions)
        assert len(results[0]) == len(sessions)

    def test_collect_entries_skips_one_unreadable_session_and_keeps_the_rest(self, tmp_path, capsys) -> None:
        now = datetime.now(timezone.utc)
        sessions = [
            Session("bad", "bad", now, now, tmp_path / "bad.jsonl", {}),
            Session("good", "good", now, now, tmp_path / "good.jsonl", {}),
        ]
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = sessions
        agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"

        def get_session_data(session: Session) -> dict[str, object]:
            if session.id == "bad":
                raise OSError("source disappeared")
            return {"messages": [{"role": "user", "content": "keep this session"}]}

        agent.get_cached_session_data.side_effect = get_session_data
        configure_session_data_lease(agent)
        progress: list[CollectProgressEvent] = []
        log_path = tmp_path / "collect.log"

        entries = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=now.date(),
            until_date=now.date(),
            local_tz=timezone.utc,
            progress_callback=progress.append,
            logger=CollectLogger(enabled=True, path=log_path, run_id="run-1"),
        )

        assert [entry.session_id for entry in entries] == ["good"]
        scan_events = [event for event in progress if isinstance(event, ScanSessionsProgress)]
        assert [(event.current, event.total) for event in scan_events] == [(0, 2), (1, 2), (2, 2)]
        captured = capsys.readouterr()
        assert (
            expect(
                Keys.WARN_SESSION_READ_SKIPPED,
                uri="codex://bad",
                error="source disappeared",
            )
            in captured.err
        )
        assert expect(Keys.WARN_SESSION_READ_FAILURES, count=1) in captured.err
        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert records[0]["event"] == "session_read_failed"
        assert records[0]["session_uri"] == "codex://bad"
        assert records[0]["error_type"] == "OSError"

    def test_collect_entries_still_fails_when_every_session_is_unreadable(self, tmp_path) -> None:
        now = datetime.now(timezone.utc)
        session = Session("bad", "bad", now, now, tmp_path / "bad.jsonl", {})
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [session]
        agent.get_session_uri.return_value = "codex://bad"
        agent.get_cached_session_data.side_effect = OSError("source disappeared")
        configure_session_data_lease(agent)

        with pytest.raises(OSError, match="source disappeared"):
            collect_entries(
                session_groups=[(agent, agent.get_sessions.return_value)],
                since_date=now.date(),
                until_date=now.date(),
                local_tz=timezone.utc,
            )

    def test_collect_entries_ignores_denied_agent_projects(self):
        now = datetime.now(timezone.utc)
        denied_root = mock.MagicMock()
        denied_root.id = "s-denied-root"
        denied_root.title = "denied-root"
        denied_root.created_at = now - timedelta(hours=1)
        denied_root.updated_at = now - timedelta(hours=1)
        denied_root.metadata = {"cwd": "/repo/fin-agent/agent"}

        denied_child = mock.MagicMock()
        denied_child.id = "s-denied-child"
        denied_child.title = "denied-child"
        denied_child.created_at = now - timedelta(hours=2)
        denied_child.updated_at = now - timedelta(hours=2)
        denied_child.metadata = {"cwd": "/repo/fin-agent/agent/subdir"}

        allowed = mock.MagicMock()
        allowed.id = "s-allowed"
        allowed.title = "allowed"
        allowed.created_at = now - timedelta(hours=3)
        allowed.updated_at = now - timedelta(hours=3)
        allowed.metadata = {"cwd": "/repo/other"}

        claude_agent = mock.MagicMock()
        claude_agent.name = "claudecode"
        claude_agent.display_name = "Claude Code"
        claude_agent.get_sessions.return_value = [denied_root, denied_child, allowed]
        claude_agent.get_session_uri.side_effect = lambda s: f"claude://{s.id}"
        claude_agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "处理仓库问题"}]}]
        }
        configure_session_data_lease(claude_agent)

        codex_session = mock.MagicMock()
        codex_session.id = "s-codex"
        codex_session.title = "codex"
        codex_session.created_at = now - timedelta(hours=4)
        codex_session.updated_at = now - timedelta(hours=4)
        codex_session.metadata = {"cwd": "/repo/fin-agent/agent"}

        codex_agent = mock.MagicMock()
        codex_agent.name = "codex"
        codex_agent.display_name = "Codex"
        codex_agent.get_sessions.return_value = [codex_session]
        codex_agent.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        codex_agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "处理 codex 会话"}]}]
        }
        configure_session_data_lease(codex_agent)

        entries = collect_entries(
            session_groups=[
                (claude_agent, claude_agent.get_sessions.return_value),
                (codex_agent, codex_agent.get_sessions.return_value),
            ],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            collect_config=CollectConfig(agent_denies={"claudecode": ("/repo/fin-agent/agent",)}),
            local_tz=timezone.utc,
        )

        assert [entry.session_id for entry in entries] == ["s-codex", "s-allowed"]
        assert [entry.agent_name for entry in entries] == ["codex", "claudecode"]

    def test_collect_deny_does_not_treat_provider_project_as_working_directory(self):
        now = datetime.now(timezone.utc)
        session = mock.MagicMock()
        session.id = "s-provider-project"
        session.title = "provider project"
        session.created_at = now - timedelta(hours=1)
        session.updated_at = now - timedelta(hours=1)
        session.source_path = Path("/provider/projects/repo/session.jsonl")
        session.metadata = {"project": "/repo/denied"}

        agent = mock.MagicMock()
        agent.name = "claudecode"
        agent.display_name = "Claude Code"
        agent.get_sessions.return_value = [session]
        agent.get_session_uri.return_value = "claude://s-provider-project"
        agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "provider project"}]}]
        }
        configure_session_data_lease(agent)

        entries = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            collect_config=CollectConfig(agent_denies={"claudecode": ("/repo/denied",)}),
            local_tz=timezone.utc,
        )

        assert [entry.session_id for entry in entries] == ["s-provider-project"]
        assert entries[0].project_directory == ""
