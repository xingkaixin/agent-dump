"""Locale-independent session age grouping."""

from datetime import datetime, timedelta, tzinfo
from enum import Enum

from agent_dump.agents.base import Session
from agent_dump.i18n import Keys
from agent_dump.time_utils import to_local_datetime


class SessionTimeGroup(Enum):
    TODAY = Keys.TIME_TODAY
    YESTERDAY = Keys.TIME_YESTERDAY
    THIS_WEEK = Keys.TIME_THIS_WEEK
    THIS_MONTH = Keys.TIME_THIS_MONTH
    OLDER = Keys.TIME_OLDER


def group_sessions_by_age(
    sessions: list[Session],
    *,
    now: datetime,
    local_tz: tzinfo,
) -> dict[SessionTimeGroup, list[Session]]:
    """Group sessions by their age relative to the current local day."""
    today = now.astimezone(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    boundaries = (
        (SessionTimeGroup.TODAY, today),
        (SessionTimeGroup.YESTERDAY, today - timedelta(days=1)),
        (SessionTimeGroup.THIS_WEEK, today - timedelta(days=7)),
        (SessionTimeGroup.THIS_MONTH, today - timedelta(days=30)),
    )
    groups = {group: [] for group in SessionTimeGroup}

    for session in sessions:
        session_time = to_local_datetime(session.created_at, local_tz)
        group = next((group for group, boundary in boundaries if session_time >= boundary), SessionTimeGroup.OLDER)
        groups[group].append(session)

    return {group: group_sessions for group, group_sessions in groups.items() if group_sessions}
