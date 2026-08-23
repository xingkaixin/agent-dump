"""Shared display projections for provider sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_dump.time_utils import to_local_datetime

if TYPE_CHECKING:
    from agent_dump.agents.base import Session, SessionFacts


def format_session_title(session: Session) -> str:
    """Format the default compact session title."""
    title = session.title[:60] + "..." if len(session.title) > 60 else session.title
    time_str = to_local_datetime(session.created_at).strftime("%Y-%m-%d %H:%M")
    return f"{title} ({time_str})"


def build_session_head(
    session: Session,
    facts: SessionFacts,
    *,
    uri: str,
    agent_display_name: str,
) -> dict[str, Any]:
    """Build the default lightweight discovery projection."""
    return {
        "uri": uri,
        "agent": agent_display_name,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "cwd_or_project": facts.display_location,
        "model": facts.model,
        "message_count": facts.message_count.value,
        "message_count_completeness": facts.message_count.completeness.value,
        "subtargets": [],
    }


def build_session_summary_fields(session: Session, facts: SessionFacts) -> dict[str, str | int | None]:
    """Build the default list and selector metadata projection."""
    return {
        "cwd_project": facts.display_location,
        "model": facts.model,
        "message_count": facts.message_count.value,
        "message_count_completeness": facts.message_count.completeness.value,
        "updated_at": to_local_datetime(session.updated_at).strftime("%Y-%m-%d %H:%M"),
    }
