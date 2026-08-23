"""Session selection, reading, and event planning for collect mode."""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, tzinfo
from pathlib import Path
import sys

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.bounded_concurrency import iter_completed_futures
from agent_dump.collect_events import chunk_collect_events, extract_collect_events
from agent_dump.collect_logging import CollectLogger
from agent_dump.collect_models import (
    CollectEntry,
    CollectProgressEvent,
    PlanChunksProgress,
    PlannedCollectEntry,
    ScanSessionsProgress,
)
from agent_dump.collect_progress import emit_collect_progress
from agent_dump.config import CollectConfig
from agent_dump.i18n import Keys, i18n
from agent_dump.query_filter import (
    QuerySpec,
    SearchSessionMatch,
    select_session_groups,
)
from agent_dump.rendering import render_session_text
from agent_dump.search_diagnostics import SearchDiagnosticSink
from agent_dump.terminal_output import render_terminal_message
from agent_dump.time_utils import get_local_timezone, get_local_today, normalize_datetime_utc, to_local_datetime

_MAX_SESSION_PARSE_WORKERS = 32
_MatchedSession = tuple[BaseAgent, Session, date]


def collect_scan_days(since_date: date, local_tz: tzinfo | None = None) -> int:
    """Return the provider window needed to cover the requested local start date."""
    resolved_local_tz = local_tz or get_local_timezone()
    return max((get_local_today(resolved_local_tz) - since_date).days + 1, 1)


def _session_local_date(session: Session, local_tz: tzinfo) -> date:
    return to_local_datetime(session.created_at, local_tz).date()


def _normalize_collect_project_path(value: str) -> Path | None:
    normalized = value.strip()
    if not normalized:
        return None
    return Path(normalized).expanduser().resolve(strict=False)


def _is_session_denied(agent: BaseAgent, session: Session, denied_roots: tuple[Path, ...]) -> bool:
    working_directory = agent.get_session_facts(session).working_directory
    session_path = _normalize_collect_project_path(str(working_directory or ""))
    if session_path is None:
        return False

    return any(session_path == denied_root or denied_root in session_path.parents for denied_root in denied_roots)


def _select_collect_sessions(
    *,
    session_groups: Sequence[tuple[BaseAgent, Sequence[Session]]],
    since_date: date,
    until_date: date,
    collect_config: CollectConfig,
    query_spec: QuerySpec | None = None,
    local_tz: tzinfo,
    diagnostic_sink: SearchDiagnosticSink | None = None,
) -> list[_MatchedSession]:
    matched_sessions: list[_MatchedSession] = []
    eligible_session_groups: list[tuple[BaseAgent, list[Session]]] = []

    for agent, sessions in session_groups:
        deny_paths = collect_config.agent_denies.get(agent.name, ())
        if deny_paths:
            denied_roots = tuple(
                denied_root
                for deny_path in deny_paths
                if (denied_root := _normalize_collect_project_path(deny_path)) is not None
            )
            if denied_roots:
                sessions = [session for session in sessions if not _is_session_denied(agent, session, denied_roots)]
        eligible_session_groups.append(
            (
                agent,
                [session for session in sessions if since_date <= _session_local_date(session, local_tz) <= until_date],
            )
        )

    candidate_matches = (
        select_session_groups(eligible_session_groups, query_spec, diagnostic_sink=diagnostic_sink)
        if query_spec is not None
        else [
            SearchSessionMatch(agent=agent, session=session, snippet=session.title, rank=0.0)
            for agent, sessions in eligible_session_groups
            for session in sessions
        ]
    )

    for match in candidate_matches:
        matched_sessions.append(
            (
                match.agent,
                match.session,
                _session_local_date(match.session, local_tz),
            )
        )

    return matched_sessions


def _read_collect_entry(matched_session: _MatchedSession) -> CollectEntry:
    agent, session, session_date = matched_session
    with agent.lease_cached_session_data(session) as session_data:
        uri = agent.get_session_uri(session)
        events, truncated = extract_collect_events(
            session_data,
            fallback_text_fn=lambda: render_session_text(uri, session_data),
        )
        return CollectEntry(
            date_value=session_date,
            created_at=session.created_at,
            agent_name=agent.name,
            agent_display_name=agent.display_name,
            session_id=session.id,
            session_title=session.title,
            session_uri=uri,
            project_directory=str(agent.get_session_facts(session).working_directory or ""),
            events=events,
            is_truncated=truncated,
        )


def _read_collect_entries(
    matched_sessions: Sequence[_MatchedSession],
    *,
    progress_callback: Callable[[CollectProgressEvent], None] | None,
    logger: CollectLogger | None,
) -> tuple[list[CollectEntry], bool]:
    entries: list[CollectEntry] = []
    has_truncated = False

    total = len(matched_sessions)
    emit_collect_progress(
        progress_callback,
        ScanSessionsProgress(current=0, total=total),
    )

    if matched_sessions:
        max_workers = min(_MAX_SESSION_PARSE_WORKERS, total)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            failed_sessions = 0
            last_error: Exception | None = None
            completed_session_uris: dict[int, str] = {}
            next_progress_index = 0
            for session_index, matched_session, future in iter_completed_futures(
                matched_sessions,
                max_pending=max_workers,
                submit=lambda item: executor.submit(_read_collect_entry, item),
            ):
                agent, session, _ = matched_session
                try:
                    entry = future.result()
                except Exception as exc:  # noqa: BLE001 - 一条损坏会话不应影响其他会话
                    failed_sessions += 1
                    last_error = exc
                    try:
                        session_uri = agent.get_session_uri(session)
                    except Exception:  # noqa: BLE001 - URI 生成失败时仍需要可识别的诊断标签
                        session_uri = f"{agent.name}:{session.id}"
                    print(
                        render_terminal_message(
                            Keys.WARN_SESSION_READ_SKIPPED,
                            uri=session_uri,
                            error=exc,
                        ),
                        file=sys.stderr,
                    )
                    if logger is not None:
                        logger.log(
                            "session_read_failed",
                            agent=agent.name,
                            session_uri=session_uri,
                            error_type=type(exc).__name__,
                            error=str(exc),
                        )
                else:
                    entries.append(entry)
                    has_truncated = has_truncated or entry.is_truncated
                    session_uri = entry.session_uri
                completed_session_uris[session_index] = session_uri
                while next_progress_index in completed_session_uris:
                    session_uri = completed_session_uris.pop(next_progress_index)
                    next_progress_index += 1
                    emit_collect_progress(
                        progress_callback,
                        ScanSessionsProgress(current=next_progress_index, total=total, session_uri=session_uri),
                    )

        if not entries and last_error is not None:
            raise last_error
        if failed_sessions:
            print(i18n.t(Keys.WARN_SESSION_READ_FAILURES, count=failed_sessions), file=sys.stderr)

    entries.sort(key=lambda item: normalize_datetime_utc(item.created_at))
    return entries, has_truncated


def collect_entries(
    *,
    session_groups: Sequence[tuple[BaseAgent, Sequence[Session]]],
    since_date: date,
    until_date: date,
    collect_config: CollectConfig | None = None,
    query_spec: QuerySpec | None = None,
    local_tz: tzinfo | None = None,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
    diagnostic_sink: SearchDiagnosticSink | None = None,
    logger: CollectLogger | None = None,
) -> tuple[list[CollectEntry], bool]:
    """Select and read collect entries for the requested range."""
    resolved_local_tz = local_tz or get_local_timezone()
    matched_sessions = _select_collect_sessions(
        session_groups=session_groups,
        since_date=since_date,
        until_date=until_date,
        collect_config=collect_config or CollectConfig(),
        query_spec=query_spec,
        local_tz=resolved_local_tz,
        diagnostic_sink=diagnostic_sink,
    )
    return _read_collect_entries(
        matched_sessions,
        progress_callback=progress_callback,
        logger=logger,
    )


def plan_collect_entries(
    entries: list[CollectEntry],
    *,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
) -> tuple[list[PlannedCollectEntry], int]:
    """Plan deterministic event chunks for each collected session."""
    total = len(entries)
    planned_entries: list[PlannedCollectEntry] = []
    total_chunks = 0
    emit_collect_progress(
        progress_callback,
        PlanChunksProgress(current=0, total=total),
    )

    for index, entry in enumerate(entries, start=1):
        chunks = tuple(chunk_collect_events(entry.events))
        total_chunks += len(chunks)
        planned_entries.append(PlannedCollectEntry(collect_entry=entry, chunks=chunks))
        emit_collect_progress(
            progress_callback,
            PlanChunksProgress(
                current=index,
                total=total,
                session_uri=entry.session_uri,
                chunk_total=total_chunks,
            ),
        )

    return planned_entries, total_chunks
