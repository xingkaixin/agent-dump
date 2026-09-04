"""Concurrent session summarization and tree reduction for collect mode."""

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, tzinfo
import sys
import threading

from agent_dump.bounded_concurrency import iter_completed_futures
from agent_dump.collect_logging import CollectLogger
from agent_dump.collect_models import (
    GROUP_SIZE,
    MAX_SUMMARY_ITEMS_PER_FIELD,
    SESSION_MERGE_LLM_THRESHOLD,
    CollectAggregate,
    CollectMode,
    CollectProgressEvent,
    CollectSummaryGroup,
    MergeSessionsProgress,
    PlannedCollectEntry,
    SessionSummaryEntry,
    StructuredSummaryContext,
    StructuredSummaryPhase,
    SummarizeChunksProgress,
    TreeReductionProgress,
)
from agent_dump.collect_progress import emit_collect_progress
from agent_dump.collect_prompts import build_collect_chunk_prompt, build_collect_merge_prompt
from agent_dump.collect_requests import StructuredSummaryRequester, request_structured_summary_from_llm
from agent_dump.collect_summary import (
    merge_summary_payloads,
    summary_payload_size,
)
from agent_dump.config import MAX_COLLECT_SUMMARY_CONCURRENCY, AIConfig
from agent_dump.i18n import Keys, i18n
from agent_dump.terminal_output import render_terminal_message


def _summary_needs_compression(payload: dict[str, list[str]]) -> bool:
    return summary_payload_size(payload) > SESSION_MERGE_LLM_THRESHOLD or any(
        len(items) > MAX_SUMMARY_ITEMS_PER_FIELD for items in payload.values()
    )


def _summarize_collect_entry(
    *,
    config: AIConfig,
    planned_entry: PlannedCollectEntry,
    timeout_seconds: int,
    local_tz: tzinfo | None,
    on_chunk_summarized: Callable[[SummarizeChunksProgress], None] | None = None,
    on_session_merged: Callable[[MergeSessionsProgress], None] | None = None,
    logger: CollectLogger | None = None,
    mode: CollectMode = CollectMode.PM,
    request_structured_summary: StructuredSummaryRequester = request_structured_summary_from_llm,
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
        payload = request_structured_summary(
            config,
            prompt,
            context=StructuredSummaryContext(
                label=f"{entry.session_uri} chunk {chunk_index + 1}/{len(chunks)}",
                phase=StructuredSummaryPhase.CHUNK_SUMMARY,
                session_uri=entry.session_uri,
                chunk_index=chunk_index + 1,
                chunk_total=len(chunks),
            ),
            timeout_seconds=timeout_seconds,
            logger=logger,
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

    merged = merge_summary_payloads(chunk_payloads, max_items_per_field=None, mode=mode)
    if len(chunk_payloads) > 1 and _summary_needs_compression(merged):
        try:
            merged = request_structured_summary(
                config,
                build_collect_merge_prompt(
                    source_uri=entry.session_uri,
                    payloads=chunk_payloads,
                    merge_label="session",
                    mode=mode,
                ),
                context=StructuredSummaryContext(
                    label=f"{entry.session_uri} session merge",
                    phase=StructuredSummaryPhase.SESSION_MERGE,
                    session_uri=entry.session_uri,
                    chunk_total=len(chunks),
                ),
                timeout_seconds=timeout_seconds,
                logger=logger,
                mode=mode,
            )
        except RuntimeError as exc:
            if logger is not None:
                logger.log(
                    "llm_merge_fallback",
                    phase=StructuredSummaryPhase.SESSION_MERGE.value,
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
        collect_entry=entry,
        summary_data=merged,
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
    request_structured_summary: StructuredSummaryRequester = request_structured_summary_from_llm,
) -> list[SessionSummaryEntry]:
    """Generate structured per-session summaries with limited concurrency."""
    if not planned_entries:
        return []

    total = len(planned_entries)
    total_chunks = sum(len(item.chunks) for item in planned_entries)
    max_workers = min(max(1, summary_concurrency), MAX_COLLECT_SUMMARY_CONCURRENCY)
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

    def _summarize(planned_entry: PlannedCollectEntry) -> SessionSummaryEntry:
        return _summarize_collect_entry(
            config=config,
            planned_entry=planned_entry,
            timeout_seconds=timeout_seconds,
            local_tz=local_tz,
            on_chunk_summarized=_mark_chunk_summarized,
            on_session_merged=_mark_session_merged,
            logger=logger,
            mode=mode,
            request_structured_summary=request_structured_summary,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for index, planned_entry, future in iter_completed_futures(
            planned_entries,
            max_pending=max_workers,
            submit=lambda item: executor.submit(_summarize, item),
        ):
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001
                failed_sessions += 1
                last_error = exc
                entry = planned_entry.collect_entry
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

    summaries = [item for item in results if item is not None]
    if not summaries and last_error is not None:
        raise last_error
    if failed_sessions:
        print(i18n.t(Keys.WARN_SESSION_SUMMARY_FAILURES, count=failed_sessions), file=sys.stderr)
    return summaries


def reduce_collect_summaries(
    *,
    config: AIConfig,
    session_summaries: list[SessionSummaryEntry],
    timeout_seconds: int = 90,
    group_size: int = GROUP_SIZE,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
    logger: CollectLogger | None = None,
    mode: CollectMode = CollectMode.PM,
    request_structured_summary: StructuredSummaryRequester = request_structured_summary_from_llm,
) -> CollectAggregate:
    """Reduce summaries only within the attribution required by the report mode."""
    working = [
        CollectSummaryGroup(
            date_value=summary.collect_entry.date_value,
            project_directory=summary.collect_entry.project_directory,
            session_uris=(summary.collect_entry.session_uri,),
            summary_data=summary.summary_data,
        )
        for summary in session_summaries
    ]
    reduction_depth = 0

    while working:
        grouped: dict[tuple[date, str, str], list[CollectSummaryGroup]] = defaultdict(list)
        for group in working:
            scope = group.session_uris[0] if mode is CollectMode.INSIGHT or not group.project_directory else ""
            grouped[(group.date_value, group.project_directory, scope)].append(group)
        if len(grouped) == len(working):
            break

        reduction_depth += 1
        next_level: list[CollectSummaryGroup] = []
        total_groups = sum((len(groups) + group_size - 1) // group_size for groups in grouped.values())
        emit_collect_progress(
            progress_callback,
            TreeReductionProgress(level=reduction_depth, current=0, total=total_groups),
        )
        group_index = 0
        for groups in grouped.values():
            for start in range(0, len(groups), group_size):
                batch = groups[start : start + group_size]
                group_index += 1
                first = batch[0]
                payloads = [group.summary_data for group in batch]
                merged = merge_summary_payloads(payloads, max_items_per_field=None, mode=mode)
                group_source = f"collect://group-level-{reduction_depth}/group-{group_index}"
                if len(batch) > 1 and _summary_needs_compression(merged):
                    try:
                        merged = request_structured_summary(
                            config,
                            build_collect_merge_prompt(
                                source_uri=group_source,
                                payloads=payloads,
                                merge_label=f"group-level-{reduction_depth}",
                                mode=mode,
                            ),
                            context=StructuredSummaryContext(
                                label=group_source,
                                phase=StructuredSummaryPhase.GROUP_MERGE,
                            ),
                            timeout_seconds=timeout_seconds,
                            logger=logger,
                            mode=mode,
                        )
                    except RuntimeError as exc:
                        if logger is not None:
                            logger.log(
                                "llm_merge_fallback",
                                phase=StructuredSummaryPhase.GROUP_MERGE.value,
                                context=group_source,
                                level=reduction_depth,
                                group_index=group_index,
                                error=str(exc),
                            )
                next_level.append(
                    CollectSummaryGroup(
                        date_value=first.date_value,
                        project_directory=first.project_directory,
                        session_uris=tuple(uri for group in batch for uri in group.session_uris),
                        summary_data=merged,
                    )
                )
                emit_collect_progress(
                    progress_callback,
                    TreeReductionProgress(level=reduction_depth, current=group_index, total=total_groups),
                )
        working = next_level

    return CollectAggregate(groups=tuple(working), reduction_depth=reduction_depth)
