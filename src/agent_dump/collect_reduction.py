"""Concurrent session summarization and tree reduction for collect mode."""

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import tzinfo
import sys
import threading

from agent_dump.collect_logging import CollectLogger
from agent_dump.collect_models import (
    GROUP_SIZE,
    SESSION_MERGE_LLM_THRESHOLD,
    CollectAggregate,
    CollectMode,
    CollectProgressEvent,
    GroupSummaryEntry,
    MergeSessionsProgress,
    PlannedCollectEntry,
    SessionSummaryEntry,
    SummarizeChunksProgress,
    TreeReductionProgress,
)
from agent_dump.collect_progress import emit_collect_progress
from agent_dump.collect_prompts import build_collect_chunk_prompt, build_collect_merge_prompt
from agent_dump.collect_requests import request_structured_summary_from_llm
from agent_dump.collect_summary import (
    dedupe_preserve_order,
    empty_summary_payload,
    merge_summary_payloads,
    summary_payload_size,
)
from agent_dump.config import AIConfig
from agent_dump.i18n import Keys, i18n
from agent_dump.terminal_output import render_terminal_message


def _summarize_collect_entry(
    *,
    config: AIConfig,
    planned_entry: PlannedCollectEntry,
    index: int,
    timeout_seconds: int,
    local_tz: tzinfo | None,
    on_chunk_summarized: Callable[[SummarizeChunksProgress], None] | None = None,
    on_session_merged: Callable[[MergeSessionsProgress], None] | None = None,
    logger: CollectLogger | None = None,
    mode: CollectMode = CollectMode.PM,
) -> SessionSummaryEntry:
    entry = planned_entry.collect_entry
    chunks = planned_entry.chunks
    chunk_payloads: list[dict[str, list[str]]] = []
    for chunk_index, chunk_events in enumerate(chunks):
        prompt = build_collect_chunk_prompt(
            entry,
            chunk_events,
            chunk_index=chunk_index,
            chunk_total=len(chunks),
            local_tz=local_tz,
            mode=mode,
        )
        payload = request_structured_summary_from_llm(
            config,
            prompt,
            context_label=f"{entry.session_uri} chunk {chunk_index + 1}/{len(chunks)}",
            timeout_seconds=timeout_seconds,
            logger=logger,
            phase="chunk_summary",
            session_uri=entry.session_uri,
            chunk_index=chunk_index + 1,
            chunk_total=len(chunks),
            mode=mode,
        )
        chunk_payloads.append(payload)
        emit_collect_progress(
            on_chunk_summarized,
            SummarizeChunksProgress(
                current=1,
                total=1,
                concurrency=1,
                session_uri=entry.session_uri,
                chunk_index=chunk_index + 1,
                chunk_total=len(chunks),
            ),
        )

    merged = merge_summary_payloads(chunk_payloads, mode=mode)
    if len(chunk_payloads) > 1 and summary_payload_size(merged) > SESSION_MERGE_LLM_THRESHOLD:
        try:
            merged = request_structured_summary_from_llm(
                config,
                build_collect_merge_prompt(entry=entry, payloads=chunk_payloads, merge_label="session", mode=mode),
                context_label=f"{entry.session_uri} session merge",
                timeout_seconds=timeout_seconds,
                logger=logger,
                phase="session_merge",
                session_uri=entry.session_uri,
                chunk_total=len(chunks),
                mode=mode,
            )
        except RuntimeError as exc:
            if logger is not None:
                logger.log(
                    "llm_merge_fallback",
                    phase="session_merge",
                    session_uri=entry.session_uri,
                    chunk_total=len(chunks),
                    error=str(exc),
                )
    emit_collect_progress(
        on_session_merged,
        MergeSessionsProgress(
            current=1,
            total=1,
            session_uri=entry.session_uri,
            chunk_total=len(chunks),
        ),
    )

    return SessionSummaryEntry(
        index=index,
        collect_entry=entry,
        summary_data=merged,
        chunk_count=len(chunks),
        source_truncated=entry.is_truncated,
    )


def summarize_collect_entries(
    *,
    config: AIConfig,
    planned_entries: list[PlannedCollectEntry],
    summary_concurrency: int,
    local_tz: tzinfo | None = None,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
    timeout_seconds: int = 90,
    logger: CollectLogger | None = None,
    mode: CollectMode = CollectMode.PM,
) -> list[SessionSummaryEntry]:
    """Generate structured per-session summaries with limited concurrency."""
    if not planned_entries:
        return []

    total = len(planned_entries)
    total_chunks = sum(len(item.chunks) for item in planned_entries)
    max_workers = max(1, summary_concurrency)
    results: list[SessionSummaryEntry | None] = [None] * total
    chunk_progress_lock = threading.Lock()
    merge_progress_lock = threading.Lock()
    summarized_chunks = 0
    merged_sessions = 0
    failed_sessions = 0
    last_error: Exception | None = None

    emit_collect_progress(
        progress_callback,
        SummarizeChunksProgress(current=0, total=total_chunks, concurrency=max_workers),
    )
    emit_collect_progress(
        progress_callback,
        MergeSessionsProgress(current=0, total=total),
    )

    def _mark_chunk_summarized(event: SummarizeChunksProgress) -> None:
        nonlocal summarized_chunks
        with chunk_progress_lock:
            summarized_chunks += event.current
            current = summarized_chunks
        emit_collect_progress(
            progress_callback,
            SummarizeChunksProgress(
                current=current,
                total=total_chunks,
                session_uri=event.session_uri,
                chunk_index=event.chunk_index,
                chunk_total=event.chunk_total,
                concurrency=max_workers,
            ),
        )

    def _mark_session_merged(event: MergeSessionsProgress) -> None:
        nonlocal merged_sessions
        with merge_progress_lock:
            merged_sessions += event.current
            current = merged_sessions
        emit_collect_progress(
            progress_callback,
            MergeSessionsProgress(
                current=current,
                total=total,
                session_uri=event.session_uri,
                chunk_total=event.chunk_total,
            ),
        )

    def _summarize(index: int, planned_entry: PlannedCollectEntry) -> SessionSummaryEntry:
        return _summarize_collect_entry(
            config=config,
            planned_entry=planned_entry,
            index=index,
            timeout_seconds=timeout_seconds,
            local_tz=local_tz,
            on_chunk_summarized=_mark_chunk_summarized,
            on_session_merged=_mark_session_merged,
            logger=logger,
            mode=mode,
        )

    future_to_index: dict[Future[SessionSummaryEntry], int] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending_entries = iter(enumerate(planned_entries))

        while len(future_to_index) < min(max_workers, total):
            index, planned_entry = next(pending_entries)
            future_to_index[executor.submit(_summarize, index, planned_entry)] = index

        while future_to_index:
            done, _ = wait(tuple(future_to_index), return_when=FIRST_COMPLETED)
            for future in done:
                index = future_to_index.pop(future)
                try:
                    results[index] = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_sessions += 1
                    last_error = exc
                    entry = planned_entries[index].collect_entry
                    print(
                        render_terminal_message(
                            Keys.WARN_SESSION_SUMMARY_SKIPPED,
                            uri=entry.session_uri,
                            error=exc,
                        ),
                        file=sys.stderr,
                    )
                    if logger is not None:
                        logger.log(
                            "session_summary_failed",
                            session_uri=entry.session_uri,
                            error=str(exc),
                        )

                try:
                    next_index, next_entry = next(pending_entries)
                except StopIteration:
                    continue
                future_to_index[executor.submit(_summarize, next_index, next_entry)] = next_index

    summaries = [item for item in results if item is not None]
    if not summaries and last_error is not None:
        raise last_error
    if failed_sessions:
        print(i18n.t(Keys.WARN_SESSION_SUMMARY_FAILURES, count=failed_sessions), file=sys.stderr)
    return summaries


def _build_summary_bucket_lines(
    session_summaries: list[SessionSummaryEntry],
    *,
    key_fn: Callable[[SessionSummaryEntry], str],
    mode: CollectMode = CollectMode.PM,
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for summary in session_summaries:
        key = key_fn(summary)
        payload = summary.summary_data
        if mode is CollectMode.INSIGHT:
            highlights = payload.get("scene", [])[:2] + payload.get("stuck", [])[:1]
        else:
            highlights = (
                payload.get("key_actions", [])[:2] + payload.get("decisions", [])[:1] + payload.get("errors", [])[:1]
            )
        line = f"{summary.collect_entry.session_title}: {'; '.join(dedupe_preserve_order(highlights, limit=4)) or '(no highlights)'}"
        grouped[key].append(line)
    return {key: dedupe_preserve_order(values, limit=6) for key, values in grouped.items()}


def reduce_collect_summaries(
    *,
    config: AIConfig,
    session_summaries: list[SessionSummaryEntry],
    timeout_seconds: int = 90,
    group_size: int = GROUP_SIZE,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
    logger: CollectLogger | None = None,
    mode: CollectMode = CollectMode.PM,
) -> CollectAggregate:
    """Reduce per-session summaries via tree reduction into one final aggregate."""
    if not session_summaries:
        return CollectAggregate(
            summary_data=empty_summary_payload(mode),
            date_summaries={},
            project_summaries={},
            session_count=0,
            reduction_depth=0,
        )

    working: list[GroupSummaryEntry] = [
        GroupSummaryEntry(level=0, summary_data=entry.summary_data, session_count=1) for entry in session_summaries
    ]
    reduction_depth = 0

    while len(working) > 1:
        reduction_depth += 1
        next_level: list[GroupSummaryEntry] = []
        total_groups = (len(working) + group_size - 1) // group_size
        emit_collect_progress(
            progress_callback,
            TreeReductionProgress(level=reduction_depth, current=0, total=total_groups),
        )
        for start in range(0, len(working), group_size):
            group = working[start : start + group_size]
            payloads = [item.summary_data for item in group]
            merged = merge_summary_payloads(payloads, mode=mode)
            if summary_payload_size(merged) > SESSION_MERGE_LLM_THRESHOLD:
                dummy_entry = session_summaries[min(start, len(session_summaries) - 1)].collect_entry
                try:
                    merged = request_structured_summary_from_llm(
                        config,
                        build_collect_merge_prompt(
                            entry=dummy_entry,
                            payloads=payloads,
                            merge_label=f"group-level-{reduction_depth}",
                            mode=mode,
                        ),
                        context_label=f"group merge level {reduction_depth} index {start // group_size + 1}",
                        timeout_seconds=timeout_seconds,
                        logger=logger,
                        phase="group_merge",
                        session_uri=dummy_entry.session_uri,
                        mode=mode,
                    )
                except RuntimeError as exc:
                    if logger is not None:
                        logger.log(
                            "llm_merge_fallback",
                            phase="group_merge",
                            session_uri=dummy_entry.session_uri,
                            level=reduction_depth,
                            group_index=start // group_size + 1,
                            error=str(exc),
                        )
            next_level.append(
                GroupSummaryEntry(
                    level=reduction_depth,
                    summary_data=merged,
                    session_count=sum(item.session_count for item in group),
                )
            )
            emit_collect_progress(
                progress_callback,
                TreeReductionProgress(
                    level=reduction_depth,
                    current=(start // group_size) + 1,
                    total=total_groups,
                ),
            )
        working = next_level

    date_summaries = _build_summary_bucket_lines(
        session_summaries,
        key_fn=lambda item: item.collect_entry.date_value.isoformat(),
        mode=mode,
    )
    project_summaries = _build_summary_bucket_lines(
        session_summaries,
        key_fn=lambda item: item.collect_entry.project_directory or "(unknown)",
        mode=mode,
    )
    return CollectAggregate(
        summary_data=working[0].summary_data,
        date_summaries=date_summaries,
        project_summaries=project_summaries,
        session_count=len(session_summaries),
        reduction_depth=reduction_depth,
    )
