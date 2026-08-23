"""Collect planning and run-stat tests."""

from datetime import date, datetime, timezone

from agent_dump.collect_models import (
    CollectEntry,
    CollectEvent,
    CollectProgressEvent,
    PlanChunksProgress,
)
from agent_dump.collect_progress import (
    build_collect_run_stats,
)
from agent_dump.collect_sessions import collect_scan_days, plan_collect_entries


class TestCollectEntries:
    def test_collect_scan_days_covers_local_start_date(self, monkeypatch):
        monkeypatch.setattr("agent_dump.collect_sessions.get_local_today", lambda _tz: date(2026, 3, 10))

        assert collect_scan_days(date(2026, 3, 5)) == 6
        assert collect_scan_days(date(2026, 3, 11)) == 1

    def test_plan_collect_entries_reports_chunk_totals(self):
        entries = [
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
                agent_name="codex",
                agent_display_name="Codex",
                session_id="s-1",
                session_uri="codex://s-1",
                session_title="task-1",
                project_directory="/repo",
                events=(
                    CollectEvent(kind="user_intent", role="user", text="a" * 1800),
                    CollectEvent(kind="assistant_key", role="assistant", text="b" * 1800),
                ),
                is_truncated=False,
            ),
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 3, 0, 0, tzinfo=timezone.utc),
                agent_name="codex",
                agent_display_name="Codex",
                session_id="s-2",
                session_uri="codex://s-2",
                session_title="task-2",
                project_directory="/repo",
                events=(CollectEvent(kind="user_intent", role="user", text="c" * 100),),
                is_truncated=False,
            ),
        ]
        progress: list[CollectProgressEvent] = []

        planned, chunk_count = plan_collect_entries(entries, progress_callback=progress.append)

        assert len(planned) == 2
        assert chunk_count == 3
        assert sum(len(item.chunks) for item in planned) == 3
        assert [event.stage for event in progress] == ["plan_chunks", "plan_chunks", "plan_chunks"]
        assert isinstance(progress[-1], PlanChunksProgress)
        assert progress[-1].chunk_total == 3

    def test_build_collect_run_stats_counts_agents_and_chunks(self):
        entries = [
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
                agent_name="codex",
                agent_display_name="Codex",
                session_id="s-1",
                session_uri="codex://s-1",
                session_title="task-1",
                project_directory="/repo",
                events=(CollectEvent(kind="user_intent", role="user", text="a" * 1800),),
                is_truncated=False,
            ),
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 3, 0, 0, tzinfo=timezone.utc),
                agent_name="claudecode",
                agent_display_name="Claude Code",
                session_id="s-2",
                session_uri="claude://s-2",
                session_title="task-2",
                project_directory="/repo",
                events=(
                    CollectEvent(kind="user_intent", role="user", text="b" * 1800),
                    CollectEvent(kind="assistant_key", role="assistant", text="c" * 1800),
                ),
                is_truncated=False,
            ),
        ]
        planned_entries, _ = plan_collect_entries(entries)

        stats = build_collect_run_stats(
            entries=entries,
            planned_entries=planned_entries,
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            summary_concurrency=4,
        )

        assert stats.since == "2026-03-01"
        assert stats.until == "2026-03-05"
        assert stats.agent_session_counts == {"Codex": 1, "Claude Code": 1}
        assert stats.session_count == 2
        assert stats.chunk_count == 3
        assert stats.concurrency == 4
