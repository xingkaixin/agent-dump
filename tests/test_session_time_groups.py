from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_dump.agents.base import Session
from agent_dump.session_time_groups import SessionTimeGroup, group_sessions_by_age


def _session(session_id: str, created_at: datetime) -> Session:
    return Session(
        id=session_id,
        title=session_id,
        created_at=created_at,
        updated_at=created_at,
        source_path=Path("/test/path"),
        metadata={},
    )


def test_group_sessions_by_age_uses_ordered_local_day_boundaries() -> None:
    local_tz = timezone(timedelta(hours=8))
    now = datetime(2026, 1, 10, 12, tzinfo=local_tz)
    sessions = [
        _session("today", datetime(2026, 1, 9, 16, tzinfo=timezone.utc)),
        _session("yesterday", datetime(2026, 1, 8, 16, tzinfo=timezone.utc)),
        _session("week", datetime(2026, 1, 3, 16, tzinfo=timezone.utc)),
        _session("month", datetime(2025, 12, 10, 16, tzinfo=timezone.utc)),
        _session("older", datetime(2025, 12, 10, 15, 59, tzinfo=timezone.utc)),
    ]

    groups = group_sessions_by_age(sessions, now=now, local_tz=local_tz)

    assert list(groups) == list(SessionTimeGroup)
    assert [[session.id for session in group] for group in groups.values()] == [
        ["today"],
        ["yesterday"],
        ["week"],
        ["month"],
        ["older"],
    ]


def test_group_sessions_by_age_omits_empty_groups() -> None:
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)

    groups = group_sessions_by_age([_session("today", now)], now=now, local_tz=timezone.utc)

    assert list(groups) == [SessionTimeGroup.TODAY]
    assert [session.id for session in groups[SessionTimeGroup.TODAY]] == ["today"]
