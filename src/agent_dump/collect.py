"""Collect mode: gather sessions and summarize with structured multi-stage reduction."""

from collections import defaultdict
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import date, tzinfo
import json
from pathlib import Path
import sys
import threading
from typing import Any
from uuid import uuid4

from agent_dump.agents.base import BaseAgent, Session, derive_session_facts
from agent_dump.collect_dates import (
    parse_user_date as parse_user_date,
    resolve_collect_date_range as resolve_collect_date_range,
)
from agent_dump.collect_events import (
    chunk_collect_events as chunk_collect_events,
    extract_collect_events as extract_collect_events,
    render_collect_event,
)
from agent_dump.collect_llm import (
    build_summary_json_schema as _build_summary_json_schema,
    is_retryable_error,
    request_structured_summary_payload_from_llm as _request_structured_summary_payload_from_llm,
    request_summary_from_llm as _request_summary_from_llm,
)
from agent_dump.collect_models import (
    GROUP_SIZE,
    SESSION_MERGE_LLM_THRESHOLD,
    SUMMARY_PARSE_RETRY_COUNT,
    SUMMARY_TRANSPORT_RETRY_COUNT,
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    CollectLogger,
    CollectMode,
    CollectProgressEvent,
    GroupSummaryEntry,
    MergeSessionsProgress,
    PlanChunksProgress,
    PlannedCollectEntry,
    ScanSessionsProgress,
    SessionSummaryEntry,
    SummarizeChunksProgress,
    TreeReductionProgress,
    collect_fields_for,
)
from agent_dump.collect_output import write_collect_markdown as write_collect_markdown
from agent_dump.collect_progress import (
    emit_collect_progress,
    truncate_log_preview,
    truncate_log_tail,
)
from agent_dump.collect_summary import (
    dedupe_preserve_order,
    empty_summary_payload,
    extract_json_object,
    merge_summary_payloads,
    normalize_summary_payload,
    serialize_summary_payload,
    summary_payload_size,
)
from agent_dump.config import AIConfig, CollectConfig
from agent_dump.i18n import Keys, i18n
from agent_dump.prompt_safety import UntrustedData, compose_summary_prompt
from agent_dump.query_filter import (
    QuerySpec,
    SearchSessionMatch,
    limit_query_session_matches,
    query_session_matches,
)
from agent_dump.scanner import AgentScanner
from agent_dump.terminal_output import render_terminal_message
from agent_dump.time_utils import get_local_timezone, get_local_today, normalize_datetime_utc, to_local_datetime

_MAX_SESSION_PARSE_WORKERS = 32


def _session_local_date(session: Session, local_tz: tzinfo) -> date:
    return to_local_datetime(session.created_at, local_tz).date()


def _normalize_collect_project_path(value: str) -> Path | None:
    normalized = value.strip()
    if not normalized:
        return None
    return Path(normalized).expanduser().resolve(strict=False)


def _is_session_denied(session: Session, deny_paths: tuple[str, ...]) -> bool:
    working_directory = derive_session_facts(session).working_directory
    session_path = _normalize_collect_project_path(str(working_directory or ""))
    if session_path is None:
        return False

    for deny_path in deny_paths:
        denied_root = _normalize_collect_project_path(deny_path)
        if denied_root is None:
            continue
        if session_path == denied_root or denied_root in session_path.parents:
            return True
    return False


def build_summary_json_schema(mode: CollectMode = CollectMode.PM) -> dict[str, Any]:
    """Build one fixed schema for collect structured summaries."""
    return _build_summary_json_schema(collect_fields_for(mode))


def collect_entries(
    *,
    agents: list[BaseAgent],
    since_date: date,
    until_date: date,
    collect_config: CollectConfig | None = None,
    query_spec: QuerySpec | None = None,
    render_session_text_fn: Callable[[str, Mapping[str, Any]], str],
    local_tz: tzinfo | None = None,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
    scanner: AgentScanner | None = None,
    logger: CollectLogger | None = None,
) -> tuple[list[CollectEntry], bool]:
    """Collect session entries for range."""
    entries: list[CollectEntry] = []
    has_truncated = False
    resolved_local_tz = local_tz or get_local_timezone()
    resolved_collect_config = collect_config or CollectConfig()
    matched_sessions: list[tuple[BaseAgent, Session, date]] = []
    candidate_matches: list[SearchSessionMatch] = []

    days_span = max((get_local_today(resolved_local_tz) - since_date).days + 1, 1)
    session_scanner = scanner if scanner is not None else AgentScanner(agents)
    for agent, sessions in session_scanner.get_sessions(days_span, agents=agents):
        deny_paths = resolved_collect_config.agent_denies.get(agent.name, ())
        if deny_paths:
            sessions = [session for session in sessions if not _is_session_denied(session, deny_paths)]
        matches = (
            query_session_matches(agent, sessions, query_spec)
            if query_spec is not None
            else [
                SearchSessionMatch(agent=agent, session=session, snippet=session.title, rank=0.0)
                for session in sessions
            ]
        )
        for match in matches:
            session = match.session
            session_date = _session_local_date(session, resolved_local_tz)
            if session_date < since_date or session_date > until_date:
                continue
            candidate_matches.append(match)

    if query_spec is not None:
        candidate_matches = limit_query_session_matches(candidate_matches, query_spec.limit)

    for match in candidate_matches:
        matched_sessions.append(
            (
                match.agent,
                match.session,
                _session_local_date(match.session, resolved_local_tz),
            )
        )

    total = len(matched_sessions)
    emit_collect_progress(
        progress_callback,
        ScanSessionsProgress(current=0, total=total),
    )

    def _collect_entry(matched_session: tuple[BaseAgent, Session, date]) -> CollectEntry:
        agent, session, session_date = matched_session
        with agent.lease_cached_session_data(session) as session_data:
            uri = agent.get_session_uri(session)
            events, truncated = extract_collect_events(
                session_data,
                fallback_text_fn=lambda: render_session_text_fn(uri, session_data),
            )
            return CollectEntry(
                date_value=session_date,
                created_at=session.created_at,
                agent_name=agent.name,
                agent_display_name=agent.display_name,
                session_id=session.id,
                session_title=session.title,
                session_uri=uri,
                project_directory=str(derive_session_facts(session).working_directory or ""),
                events=events,
                is_truncated=truncated,
            )

    if matched_sessions:
        max_workers = min(_MAX_SESSION_PARSE_WORKERS, total)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_collect_entry, matched_session) for matched_session in matched_sessions]
            failed_sessions = 0
            last_error: Exception | None = None
            for index, (matched_session, future) in enumerate(
                zip(matched_sessions, futures, strict=True),
                start=1,
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
                emit_collect_progress(
                    progress_callback,
                    ScanSessionsProgress(current=index, total=total, session_uri=session_uri),
                )

        if not entries and last_error is not None:
            raise last_error
        if failed_sessions:
            print(i18n.t(Keys.WARN_SESSION_READ_FAILURES, count=failed_sessions), file=sys.stderr)

    entries.sort(key=lambda item: normalize_datetime_utc(item.created_at))
    return entries, has_truncated


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


def build_collect_chunk_prompt(
    entry: CollectEntry,
    chunk_events: tuple[CollectEvent, ...],
    *,
    chunk_index: int,
    chunk_total: int,
    local_tz: tzinfo | None = None,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build prompt for a chunk-level structured summary."""
    resolved_local_tz = local_tz or get_local_timezone()
    fields = collect_fields_for(mode)
    if mode is CollectMode.INSIGHT:
        lines = [
            "任务：从用户视角提取给定 chunk 中的关键事实片段。",
            "请只基于给定 chunk 内容输出 JSON 对象，不要输出 Markdown，不要补充解释。",
            f"JSON 必须只包含这些字段: {', '.join(fields)}。",
            "每个字段都必须是字符串数组；没有内容时返回空数组。",
            "字段说明：",
            "- scene: 用户想做什么——目标、意图、正在推进的事。每条一句话。",
            "- stuck: 用户卡在哪——遇到的障碍、反复尝试的地方、报错、犹豫。每条一句话。",
            "- turning: 转折点——思路或行为发生明确变化的时刻（换方案、换工具、换角度）。每条一句话。",
            "要求：",
            "1. 只基于会话中的事实，不要编造。",
            "2. 不要做价值判断或锐评，只描述发生了什么。",
            "3. 同一事实不要换说法重复写。",
            "4. 如果某个字段没有对应内容，返回空数组。",
            "5. 字符串内部如需引用英文双引号，必须按 JSON 规则转义，或改用中文引号。",
        ]
    else:
        lines = [
            "任务：为给定 chunk 生成严谨的工作记录结构化摘要。",
            "请只基于给定 chunk 内容输出 JSON 对象，不要输出 Markdown，不要补充解释。",
            f"JSON 必须只包含这些字段: {', '.join(fields)}。",
            "每个字段都必须是字符串数组；没有内容时返回空数组。",
            "要求：",
            "1. 只保留事实，不要编造。",
            "2. 同一事实不要换说法重复写。",
            "3. errors 只放错误/异常/失败。",
            "4. files 只放文件路径。",
            "5. tools_used 只放工具名。",
            "6. 字符串内部如需引用英文双引号，必须按 JSON 规则转义，或改用中文引号。",
        ]
    metadata_body = "\n".join(
        [
            f"title: {entry.session_title}",
            f"project_directory: {entry.project_directory or '(unknown)'}",
            f"created_at: {to_local_datetime(entry.created_at, resolved_local_tz).isoformat()}",
            f"chunk: {chunk_index + 1}/{chunk_total}",
        ]
    )
    events_body = "\n".join(render_collect_event(event) for event in chunk_events)
    return compose_summary_prompt(
        lines,
        data=(
            UntrustedData(
                kind="session_metadata",
                source=f"{entry.session_uri}#chunk-{chunk_index + 1}/metadata",
                body=metadata_body,
            ),
            UntrustedData(
                kind="session_events",
                source=f"{entry.session_uri}#chunk-{chunk_index + 1}/events",
                body=events_body,
            ),
        ),
    )


def build_collect_merge_prompt(
    *,
    entry: CollectEntry,
    payloads: list[dict[str, list[str]]],
    merge_label: str,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build prompt for session/group structured merge when deterministic merge is too large."""
    fields = collect_fields_for(mode)
    lines = [
        "任务：严谨归并给定的多个结构化摘要。",
        "请把下面多个 JSON 摘要归并成一个 JSON 对象。",
        f"输出 JSON 仍然只能包含这些字段: {', '.join(fields)}。",
        "每个字段必须是字符串数组；没有内容时返回空数组。",
        "要求：去重、保留关键事实、压缩重复表述，不要输出字段之外的内容。",
        "",
        "归并上下文：",
        f"- merge_label: {merge_label}",
    ]
    data = tuple(
        UntrustedData(
            kind="untrusted_derived_summary",
            source=(
                f"{entry.session_uri}#summary-{index}"
                if merge_label == "session"
                else f"collect://{merge_label}/summary/{index}"
            ),
            body=serialize_summary_payload(payload),
        )
        for index, payload in enumerate(payloads, start=1)
    )
    return compose_summary_prompt(lines, data=data)


def request_summary_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int = 90,
    retry_count: int = 1,
) -> str:
    """Call provider API and return markdown summary, retrying transient failures.

    最终 Markdown 渲染是管线末端的单次调用，失败会丢弃整个运行的成果，因此默认重试一次。
    """
    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            return _request_summary_from_llm(config, prompt, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            # 只重试可能因重发而成功的失败。对 400/401/403 这类永久错误重发非幂等的
            # POST，只是把每个 chunk 的延迟与计费翻倍。
            if attempt < retry_count and not is_retryable_error(exc):
                break
    if last_error is None:
        raise RuntimeError("summary request failed without an error")
    raise last_error


def _build_structured_summary_retry_prompt(
    *,
    original_prompt: str,
    invalid_response: str,
    mode: CollectMode,
    request_source: str,
) -> str:
    fields = collect_fields_for(mode)
    retry = compose_summary_prompt(
        (
            "上一轮输出不是合法 JSON，不能被解析。",
            "请重新生成完整结果，仍然只输出一个 JSON 对象。",
            f"JSON 只能包含这些字段: {', '.join(fields)}。",
            "每个字段必须是字符串数组；没有内容时返回空数组。",
            "不要输出 Markdown，不要解释，不要保留无效片段。",
            "字符串内部如需引用英文双引号，必须按 JSON 规则转义，或改用中文引号。",
        ),
        data=(
            UntrustedData(
                kind="untrusted_derived_summary",
                source=request_source,
                body=truncate_log_preview(invalid_response, limit=1200),
            ),
        ),
    )
    return "\n\n".join((original_prompt, retry))


def request_structured_summary_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    context_label: str,
    timeout_seconds: int = 90,
    parse_retry_count: int = SUMMARY_PARSE_RETRY_COUNT,
    transport_retry_count: int = SUMMARY_TRANSPORT_RETRY_COUNT,
    logger: CollectLogger | None = None,
    phase: str = "structured_summary",
    session_uri: str | None = None,
    chunk_index: int | None = None,
    chunk_total: int | None = None,
    mode: CollectMode = CollectMode.PM,
) -> dict[str, list[str]]:
    """Call LLM and parse one structured summary payload."""
    summary_fields = collect_fields_for(mode)
    current_prompt = prompt
    parse_attempt = 0
    transport_attempt = 0
    while True:
        request_id = str(uuid4())
        attempt_fields = {
            "parse_attempt": parse_attempt + 1,
            "parse_attempt_limit": parse_retry_count + 1,
            "transport_attempt": transport_attempt + 1,
            "transport_attempt_limit": transport_retry_count + 1,
        }
        if logger is not None:
            logger.log(
                "llm_request",
                request_id=request_id,
                phase=phase,
                provider=config.provider,
                model=config.model,
                session_uri=session_uri,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
                prompt_chars=len(current_prompt),
                **attempt_fields,
            )
        try:
            response = request_structured_summary_payload_from_llm(
                config,
                current_prompt,
                timeout_seconds=timeout_seconds,
                summary_fields=summary_fields,
            )
        except Exception as exc:  # noqa: BLE001
            retryable = is_retryable_error(exc)
            will_retry = retryable and transport_attempt < transport_retry_count
            if logger is not None:
                logger.log(
                    "llm_request_error",
                    request_id=request_id,
                    phase=phase,
                    provider=config.provider,
                    model=config.model,
                    session_uri=session_uri,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    error=str(exc),
                    retryable=retryable,
                    will_retry=will_retry,
                    retry_kind="transport" if will_retry else None,
                    **attempt_fields,
                )
            if will_retry:
                transport_attempt += 1
                continue
            raise RuntimeError(f"{context_label}: structured summary request failed: {exc}") from exc
        if logger is not None:
            logger.log(
                "llm_response",
                request_id=request_id,
                phase=phase,
                provider=config.provider,
                model=config.model,
                session_uri=session_uri,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
                response_chars=len(response),
                **attempt_fields,
            )
        try:
            return normalize_summary_payload(extract_json_object(response), mode=mode)
        except Exception as exc:  # noqa: BLE001
            will_retry = parse_attempt < parse_retry_count
            if logger is not None:
                logger.log(
                    "llm_parse_error",
                    request_id=request_id,
                    phase=phase,
                    provider=config.provider,
                    model=config.model,
                    session_uri=session_uri,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    error=str(exc),
                    response_chars=len(response),
                    response_preview=truncate_log_preview(response),
                    response_tail_preview=truncate_log_tail(response),
                    will_retry=will_retry,
                    retry_kind="parse_correction" if will_retry else None,
                    **attempt_fields,
                )
            if not will_retry:
                raise RuntimeError(f"{context_label}: invalid structured summary response: {exc}") from exc
            parse_attempt += 1
            transport_attempt = 0
            current_prompt = _build_structured_summary_retry_prompt(
                original_prompt=prompt,
                invalid_response=response,
                mode=mode,
                request_source=f"{phase}://request/{request_id}",
            )


def request_structured_summary_payload_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int = 90,
    summary_fields: tuple[str, ...] | None = None,
) -> str:
    """Call provider API and return one structured summary payload string."""
    return _request_structured_summary_payload_from_llm(
        config,
        prompt,
        timeout_seconds=timeout_seconds,
        summary_fields=summary_fields,
    )


def build_collect_session_prompt(
    entry: CollectEntry,
    *,
    source_truncated: bool,
    local_tz: tzinfo | None = None,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build compatibility prompt string for one whole session."""
    chunks = chunk_collect_events(entry.events)
    return build_collect_chunk_prompt(
        entry,
        chunks[0],
        chunk_index=0,
        chunk_total=len(chunks),
        local_tz=local_tz,
        mode=mode,
    ) + ("\n\n注意：原始 session 内容在事件提取阶段已截断。" if source_truncated else "")


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


def build_collect_final_prompt(
    *,
    since_date: date,
    until_date: date,
    aggregate: CollectAggregate,
    has_truncated: bool,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build final collect markdown prompt from the final aggregate."""
    if mode is CollectMode.INSIGHT:
        lines = [
            "任务：从用户视角整理给定聚合数据中的关键事实片段。",
            "请基于给定的结构化聚合数据输出 Markdown，只摆事实，不做评价。",
            "必须严格使用以下结构：",
            f"# 作者洞察（{since_date.isoformat()} ~ {until_date.isoformat()}）",
            "",
            "## 洞察",
            "",
            "每条洞察用以下格式（scene/stuck/turning 三个维度交叉组合，不要求每条都齐备）：",
            "### [简短标题]",
            "- **想做什么**: [用户的目标或意图]",
            "- **卡在哪**: [遇到的障碍或反复尝试的地方]",
            "- **转折点**: [思路或行为发生明确变化的时刻]",
            "",
            "要求：",
            "1. 从聚合数据中提炼，同一 session 的相关事实合并。",
            "2. 只描述事实，不做价值判断。",
            "3. 如果某个维度没有内容，省略该行。",
        ]
    else:
        lines = [
            "任务：分析给定的结构化聚合数据并生成工作记录。",
            "请基于给定的结构化聚合数据输出 Markdown，总结重点工作。",
            "必须严格使用以下结构：",
            f"# 时段工作总结（{since_date.isoformat()} ~ {until_date.isoformat()}）",
            "## 按日期",
            "## 按项目/目录",
            "## 重点事项（决策/风险/阻塞）",
            "## 产出清单",
            "## 下一步建议",
            "要求：避免空话，按事实归纳；同一事项合并去重；可按优先级标注。",
        ]

    lines.extend(
        [
            "",
            f"- session_count: {aggregate.session_count}",
            f"- reduction_depth: {aggregate.reduction_depth}",
        ]
    )
    if has_truncated:
        lines.append("注意：部分 session 在事件提取阶段达到预算上限，最终结论可能遗漏低优先级细节。")

    data = [
        UntrustedData(
            kind="untrusted_derived_summary",
            source="collect://final/aggregate",
            body=serialize_summary_payload(aggregate.summary_data),
        )
    ]
    data.extend(
        UntrustedData(
            kind="date_summary_bucket",
            source=f"collect://final/date/{index}",
            body=json.dumps({"bucket": bucket, "values": values}, ensure_ascii=False),
        )
        for index, (bucket, values) in enumerate(aggregate.date_summaries.items(), start=1)
    )
    data.extend(
        UntrustedData(
            kind="project_summary_bucket",
            source=f"collect://final/project/{index}",
            body=json.dumps({"bucket": bucket, "values": values}, ensure_ascii=False),
        )
        for index, (bucket, values) in enumerate(aggregate.project_summaries.items(), start=1)
    )
    return compose_summary_prompt(lines, data=tuple(data))
