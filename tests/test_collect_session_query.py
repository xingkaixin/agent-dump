"""Collect session date and query filtering tests."""

from datetime import date, datetime, timedelta, timezone
import gc
import json
from pathlib import Path
import threading
import tracemalloc
from unittest import mock

from collect_test_support import configure_session_data_lease, make_query_spec

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.collect import (
    _MAX_SESSION_PARSE_WORKERS,
    collect_entries,
)


class TestCollectEntries:
    def test_collect_entries_filters_by_user_local_date(self):
        local_tz = timezone(timedelta(hours=8))
        utc_time = datetime(2026, 3, 4, 18, 0, tzinfo=timezone.utc)
        session = mock.MagicMock()
        session.id = "cross-day"
        session.title = "cross-day"
        session.created_at = utc_time
        session.updated_at = utc_time
        session.metadata = {"cwd": "/repo/cross-day"}

        agent = mock.MagicMock()
        agent.name = "opencode"
        agent.display_name = "OpenCode"
        agent.get_sessions.return_value = [session]
        agent.get_session_uri.return_value = "opencode://cross-day"
        agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "修复"}]}]
        }
        configure_session_data_lease(agent)

        entries, truncated = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=date(2026, 3, 5),
            until_date=date(2026, 3, 5),
            render_session_text_fn=lambda uri, data: f"# Session Dump\n{uri}\n",
            local_tz=local_tz,
        )

        assert truncated is False
        assert len(entries) == 1
        assert entries[0].date_value == date(2026, 3, 5)
        assert entries[0].session_id == "cross-day"

    def test_collect_entries_applies_path_scoped_query(self):
        now = datetime.now(timezone.utc)
        matching = mock.MagicMock()
        matching.id = "s-match"
        matching.title = "match"
        matching.created_at = now - timedelta(hours=1)
        matching.updated_at = now - timedelta(hours=1)
        matching.metadata = {"cwd": "/repo/app"}

        other = mock.MagicMock()
        other.id = "s-other"
        other.title = "other"
        other.created_at = now - timedelta(hours=2)
        other.updated_at = now - timedelta(hours=2)
        other.metadata = {"cwd": "/repo/other"}

        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [matching, other]
        agent.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        agent.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "修复仓库问题"}]}]
        }
        configure_session_data_lease(agent)

        entries, truncated = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            query_spec=make_query_spec(project_path=Path("/repo/app")),
            render_session_text_fn=lambda uri, data: f"{uri} {json.dumps(data)}",
            local_tz=timezone.utc,
        )

        assert truncated is False
        assert [entry.session_id for entry in entries] == ["s-match"]

    def test_collect_entries_applies_global_limit_after_filtering(self):
        now = datetime.now(timezone.utc)
        newer = mock.MagicMock()
        newer.id = "s-new"
        newer.title = "new"
        newer.created_at = now - timedelta(minutes=30)
        newer.updated_at = now - timedelta(minutes=30)
        newer.metadata = {"cwd": "/repo/app"}

        older = mock.MagicMock()
        older.id = "s-old"
        older.title = "old"
        older.created_at = now - timedelta(hours=2)
        older.updated_at = now - timedelta(hours=2)
        older.metadata = {"cwd": "/repo/app"}

        agent_a = mock.MagicMock()
        agent_a.name = "codex"
        agent_a.display_name = "Codex"
        agent_a.get_sessions.return_value = [older]
        agent_a.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        agent_a.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "refactor app"}]}]
        }
        configure_session_data_lease(agent_a)

        agent_b = mock.MagicMock()
        agent_b.name = "kimi"
        agent_b.display_name = "Kimi"
        agent_b.get_sessions.return_value = [newer]
        agent_b.get_session_uri.side_effect = lambda s: f"kimi://{s.id}"
        agent_b.get_cached_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "refactor app"}]}]
        }
        configure_session_data_lease(agent_b)

        entries, truncated = collect_entries(
            session_groups=[
                (agent_a, agent_a.get_sessions.return_value),
                (agent_b, agent_b.get_sessions.return_value),
            ],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            query_spec=make_query_spec(keyword="refactor", limit=1),
            render_session_text_fn=lambda uri, data: f"{uri} {json.dumps(data)}",
            local_tz=timezone.utc,
        )

        assert truncated is False
        assert [(entry.agent_name, entry.session_id) for entry in entries] == [("kimi", "s-new")]

    def test_collect_entries_projects_only_role_evidence_matches(self):
        now = datetime.now(timezone.utc)
        matching = mock.MagicMock()
        matching.id = "s-assistant"
        matching.title = "assistant match"
        matching.created_at = now - timedelta(minutes=30)
        matching.updated_at = now - timedelta(minutes=30)
        matching.metadata = {"cwd": "/repo/app"}

        excluded = mock.MagicMock()
        excluded.id = "s-user"
        excluded.title = "user match"
        excluded.created_at = now - timedelta(hours=1)
        excluded.updated_at = now - timedelta(hours=1)
        excluded.metadata = {"cwd": "/repo/app"}

        session_data = {
            "s-assistant": {
                "messages": [
                    {
                        "role": "assistant",
                        "parts": [{"type": "text", "text": "fatal assistant evidence"}],
                    }
                ]
            },
            "s-user": {"messages": [{"role": "user", "parts": [{"type": "text", "text": "fatal user evidence"}]}]},
        }
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [matching, excluded]
        agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
        agent.get_cached_session_data.side_effect = lambda session: session_data[session.id]
        configure_session_data_lease(agent)

        entries, truncated = collect_entries(
            session_groups=[(agent, agent.get_sessions.return_value)],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            query_spec=make_query_spec(keyword="fatal", roles={"assistant"}),
            render_session_text_fn=lambda uri, data: f"{uri} {json.dumps(data)}",
            local_tz=timezone.utc,
        )

        assert truncated is False
        assert [entry.session_id for entry in entries] == ["s-assistant"]

    def test_full_payload_memory_does_not_accumulate_after_event_projection(self) -> None:
        payload_size = 256 * 1024
        now = datetime.now(timezone.utc)
        sessions = [
            Session(
                id=f"session-{index}",
                title=f"Session {index}",
                created_at=now - timedelta(minutes=index),
                updated_at=now - timedelta(minutes=index),
                source_path=Path(f"/missing/session-{index}.jsonl"),
                metadata={},
            )
            for index in range(100)
        ]

        class LargePayloadAgent(BaseAgent):
            def __init__(self) -> None:
                super().__init__(name="codex", display_name="Codex")
                self.data_reads = 0
                self._reads_lock = threading.Lock()

            def scan(self) -> list[Session]:
                return sessions

            def is_available(self) -> bool:
                return True

            def get_sessions(self, days: int | None = 7) -> list[Session]:
                return sessions

            def get_session_data(self, session: Session) -> dict[str, object]:
                with self._reads_lock:
                    self.data_reads += 1
                return {
                    "padding": bytearray(payload_size),
                    "messages": [{"role": "user", "content": f"work on {session.id}"}],
                }

        agent = LargePayloadAgent()
        gc.collect()
        tracemalloc.start()
        baseline, _ = tracemalloc.get_traced_memory()
        entries, truncated = collect_entries(
            session_groups=[(agent, sessions)],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            render_session_text_fn=lambda _uri, _data: "",
            local_tz=timezone.utc,
        )
        gc.collect()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert truncated is False
        assert len(entries) == len(sessions)
        assert agent.data_reads == len(sessions)
        assert not agent._session_data_cache._entries
        assert current - baseline < payload_size * 8
        assert peak - baseline < payload_size * (_MAX_SESSION_PARSE_WORKERS + 16)
