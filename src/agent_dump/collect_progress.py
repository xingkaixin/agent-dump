"""Logging, progress reporting and run statistics for collect.

从 collect.py 拆出：这层是 collect 与 collect_workflow 共享的纯管道，不参与
事件/摘要算法。
"""

from collections.abc import Callable
from datetime import date
from typing import TypeVar
from uuid import uuid4

from agent_dump.collect_models import (
    MAX_LOG_PREVIEW_CHARS,
    CollectEntry,
    CollectLogger,
    CollectProgressEvent,
    CollectRunStats,
    PlannedCollectEntry,
)
from agent_dump.config import LoggingConfig

ProgressEventT = TypeVar("ProgressEventT", bound=CollectProgressEvent)


def truncate_log_preview(text: str, limit: int = MAX_LOG_PREVIEW_CHARS) -> str:
    """Return the bounded leading portion of text used in collect logs."""
    normalized = text.strip()
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3].rstrip()}..."


def truncate_log_tail(text: str, limit: int = MAX_LOG_PREVIEW_CHARS) -> str:
    """Return the bounded trailing portion of text used in collect logs."""
    normalized = text.strip()
    return normalized if len(normalized) <= limit else f"...{normalized[-limit + 3 :].lstrip()}"


def create_collect_logger(config: LoggingConfig | None) -> CollectLogger:
    """Create a collect logger from config."""
    if config is None or not config.enabled:
        return CollectLogger(enabled=False, run_id=str(uuid4()))
    return CollectLogger(enabled=True, path=config.path, run_id=str(uuid4()))


def emit_collect_progress(
    progress_callback: Callable[[ProgressEventT], None] | None,
    event: ProgressEventT,
) -> None:
    """Emit one collect progress event when callback is configured."""
    if progress_callback is not None:
        progress_callback(event)


def build_collect_run_stats(
    *,
    entries: list[CollectEntry],
    planned_entries: list[PlannedCollectEntry],
    since_date: date,
    until_date: date,
    summary_concurrency: int,
) -> CollectRunStats:
    """Build one user-facing collect workload summary."""
    agent_session_counts: dict[str, int] = {}
    for entry in entries:
        agent_session_counts[entry.agent_display_name] = agent_session_counts.get(entry.agent_display_name, 0) + 1

    return CollectRunStats(
        since=since_date.isoformat(),
        until=until_date.isoformat(),
        agent_session_counts=agent_session_counts,
        session_count=len(entries),
        chunk_count=sum(len(item.chunks) for item in planned_entries),
        concurrency=max(1, summary_concurrency),
    )
