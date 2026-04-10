"""Collect mode: gather sessions and summarize with structured multi-stage reduction."""

from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import date, datetime, tzinfo
import json
from pathlib import Path
import re
import threading
from typing import Any, cast
from uuid import uuid4

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.collect_llm import (
    build_summary_json_schema as _build_summary_json_schema,
    request_structured_summary_payload_from_llm as _request_structured_summary_payload_from_llm,
    request_summary_from_llm as _request_summary_from_llm,
)
from agent_dump.collect_models import (
    CHUNK_TARGET_CHARS,
    EVENT_EXTRACT_CHAR_BUDGET,
    GROUP_SIZE,
    MAX_LOG_PREVIEW_CHARS,
    MAX_SUMMARY_ITEMS_PER_FIELD,
    SESSION_MERGE_LLM_THRESHOLD,
    SUMMARY_FIELDS,
    SUMMARY_PARSE_RETRY_COUNT,
    SUPPORTED_DATE_FORMATS,
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    CollectLogger,
    CollectProgressEvent,
    CollectRunStats,
    GroupSummaryEntry,
    PlannedCollectEntry,
    SessionSummaryEntry,
)
from agent_dump.config import AIConfig, CollectConfig, LoggingConfig
from agent_dump.message_filter import get_text_content_parts, should_filter_message_for_export
from agent_dump.query_filter import QuerySpec, filter_sessions_by_query
from agent_dump.time_utils import get_local_timezone, get_local_today, normalize_datetime_utc, to_local_datetime

GREETING_PATTERN = re.compile(r"^(hi|hello|thanks|thank you|你好|您好|好的|收到|明白|嗯嗯|ok\b)", re.IGNORECASE)
DECISION_PATTERN = re.compile(r"(决定|采用|改成|切换|方案|fix|修复|处理|实现|完成|done|resolved?)", re.IGNORECASE)
ERROR_PATTERN = re.compile(
    r"(error|exception|traceback|failed|failure|bug|报错|错误|异常|失败|崩溃|panic|not found)",
    re.IGNORECASE,
)
QUESTION_PATTERN = re.compile(r"(\?$|是否|要不要|需要|待确认|todo|待办|next)", re.IGNORECASE)
CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]+?```")
PATH_PATTERN = re.compile(
    r"(?:(?:[A-Za-z]:)?[\\/][^\s'\"`]+|(?:\./|\../|~?/)?[\w.-]+(?:/[\w.-]+)+)",
)
SUMMARY_JSON_PATTERN = re.compile(r"```json\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


def parse_user_date(value: str) -> date:
    """Parse date from supported input formats."""
    normalized = value.strip()
    for fmt in SUPPORTED_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    raise ValueError(f"invalid date format: {value}")


def resolve_collect_date_range(
    since: str | None,
    until: str | None,
    *,
    today: date | None = None,
    local_tz: tzinfo | None = None,
) -> tuple[date, date]:
    """Resolve effective [since, until] date range."""
    effective_today = today or get_local_today(local_tz)

    if not since and not until:
        return effective_today, effective_today

    if since and until:
        start = parse_user_date(since)
        end = parse_user_date(until)
        if start > end:
            raise ValueError("since_after_until")
        return start, end

    if since:
        start = parse_user_date(since)
        end = effective_today
        if start > end:
            raise ValueError("since_after_until")
        return start, end

    end = parse_user_date(until or "")
    start = date(end.year, end.month, 1)
    if start > end:
        raise ValueError("since_after_until")
    return start, end


def _session_local_date(session: Session, local_tz: tzinfo) -> date:
    return to_local_datetime(session.created_at, local_tz).date()


def _normalize_collect_project_path(value: str) -> Path | None:
    normalized = value.strip()
    if not normalized:
        return None
    return Path(normalized).expanduser().resolve(strict=False)


def _is_session_denied(session: Session, deny_paths: tuple[str, ...]) -> bool:
    project_directory = str(session.metadata.get("cwd") or session.metadata.get("directory") or "")
    session_path = _normalize_collect_project_path(project_directory)
    if session_path is None:
        return False

    for deny_path in deny_paths:
        denied_root = _normalize_collect_project_path(deny_path)
        if denied_root is None:
            continue
        if session_path == denied_root or denied_root in session_path.parents:
            return True
    return False


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate_log_preview(text: str, limit: int = MAX_LOG_PREVIEW_CHARS) -> str:
    normalized = text.strip()
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3].rstrip()}..."


def _truncate_excerpt(text: str, limit: int = 280) -> str:
    normalized = text.strip()
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3].rstrip()}..."


def _dedupe_preserve_order(values: Iterable[str], *, limit: int = MAX_SUMMARY_ITEMS_PER_FIELD) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized:
            continue
        lowered = normalized.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def empty_summary_payload() -> dict[str, list[str]]:
    """Create one empty structured summary payload."""
    return {field_name: [] for field_name in SUMMARY_FIELDS}


def normalize_summary_payload(payload: dict[str, Any]) -> dict[str, list[str]]:
    """Normalize unknown payload to the fixed summary schema."""
    normalized = empty_summary_payload()
    for field_name in SUMMARY_FIELDS:
        raw_value = payload.get(field_name, [])
        values: list[str]
        if isinstance(raw_value, list):
            values = [str(item) for item in raw_value if str(item).strip()]
        elif isinstance(raw_value, str) and raw_value.strip():
            values = [raw_value]
        else:
            values = []
        normalized[field_name] = _dedupe_preserve_order(values)
    return normalized


def merge_summary_payloads(
    payloads: Iterable[dict[str, list[str]]],
    *,
    max_items_per_field: int = MAX_SUMMARY_ITEMS_PER_FIELD,
) -> dict[str, list[str]]:
    """Merge structured summaries deterministically."""
    merged = empty_summary_payload()
    for field_name in SUMMARY_FIELDS:
        items: list[str] = []
        for payload in payloads:
            items.extend(payload.get(field_name, []))
        merged[field_name] = _dedupe_preserve_order(items, limit=max_items_per_field)
    return merged


def _summary_payload_size(payload: dict[str, list[str]]) -> int:
    return sum(len(items) for items in payload.values())


def _extract_json_object(text: str) -> dict[str, Any]:
    match = SUMMARY_JSON_PATTERN.search(text)
    candidates = [match.group(1)] if match else []
    candidates.append(text.strip())

    stripped = text.strip()
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidates.append(stripped[first_brace : last_brace + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return cast(dict[str, Any], loaded)
    raise ValueError("response is not valid JSON object")


def _serialize_summary_payload(payload: dict[str, list[str]]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_summary_json_schema() -> dict[str, Any]:
    """Build one fixed schema for collect structured summaries."""
    return _build_summary_json_schema()


def create_collect_logger(config: LoggingConfig | None) -> CollectLogger:
    """Create a collect logger from config."""
    if config is None or not config.enabled:
        return CollectLogger(enabled=False, run_id=str(uuid4()))
    return CollectLogger(enabled=True, path=config.path, run_id=str(uuid4()))


def emit_collect_progress(
    progress_callback: Callable[[CollectProgressEvent], None] | None,
    *,
    stage: str,
    current: int,
    total: int,
    message: str,
    session_uri: str | None = None,
    chunk_index: int | None = None,
    chunk_total: int | None = None,
    level: int | None = None,
    session_count: int | None = None,
    chunk_count: int | None = None,
    concurrency: int | None = None,
    since: str | None = None,
    until: str | None = None,
    agent_session_counts: dict[str, int] | None = None,
) -> None:
    """Emit one collect progress event when callback is configured."""
    if progress_callback is None:
        return
    progress_callback(
        CollectProgressEvent(
            stage=stage,
            current=current,
            total=total,
            message=message,
            session_uri=session_uri,
            chunk_index=chunk_index,
            chunk_total=chunk_total,
            level=level,
            session_count=session_count,
            chunk_count=chunk_count,
            concurrency=concurrency,
            since=since,
            until=until,
            agent_session_counts=agent_session_counts,
        )
    )


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


def _find_paths_in_text(text: str) -> list[str]:
    candidates = [match.group(0).strip(".,:;)]}") for match in PATH_PATTERN.finditer(text)]
    return _dedupe_preserve_order(candidates, limit=6)


def _extract_part_text(part: dict[str, Any]) -> str:
    part_type = str(part.get("type", ""))
    if part_type in {"text", "reasoning"}:
        return str(part.get("text", "")).strip()
    if part_type == "plan":
        return str(part.get("input", "")).strip()
    if part_type == "tool":
        tool_name = str(part.get("tool") or part.get("name") or "").strip()
        title = str(part.get("title", "")).strip()
        state = part.get("state")
        output = part.get("output")
        fragments = [fragment for fragment in (tool_name, title) if fragment]
        if isinstance(state, (dict, list)):
            fragments.append(json.dumps(state, ensure_ascii=False))
        elif isinstance(state, str) and state.strip():
            fragments.append(state.strip())
        if isinstance(output, (dict, list)):
            fragments.append(json.dumps(output, ensure_ascii=False))
        elif isinstance(output, str) and output.strip():
            fragments.append(output.strip())
        return " | ".join(fragment for fragment in fragments if fragment)
    return ""


def _build_collect_event(kind: str, role: str, text: str, *, tool_name: str | None = None) -> CollectEvent | None:
    normalized_text = _truncate_excerpt(text)
    if not normalized_text:
        return None
    files = tuple(_find_paths_in_text(normalized_text))
    return CollectEvent(kind=kind, role=role, text=normalized_text, files=files, tool_name=tool_name)


def _classify_text_event(role: str, text: str) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None
    if GREETING_PATTERN.match(normalized) and len(normalized) <= 60:
        return None
    if role == "user":
        return "user_intent"
    if role == "tool":
        return "error" if ERROR_PATTERN.search(normalized) else "tool_result"
    if CODE_BLOCK_PATTERN.search(text):
        return "code"
    if ERROR_PATTERN.search(normalized):
        return "error"
    if QUESTION_PATTERN.search(normalized):
        return "open_question"
    if DECISION_PATTERN.search(normalized):
        return "decision"
    if role == "assistant":
        return "assistant_key"
    return "message"


def extract_collect_events(
    session_data: dict[str, Any],
    *,
    fallback_text: str = "",
    char_budget: int = EVENT_EXTRACT_CHAR_BUDGET,
) -> tuple[tuple[CollectEvent, ...], bool]:
    """Extract deterministic high-signal events from one session."""
    events: list[CollectEvent] = []
    used_chars = 0
    truncated = False
    messages = session_data.get("messages", [])

    def _append_event(event: CollectEvent | None) -> None:
        nonlocal used_chars, truncated
        if event is None:
            return
        event_size = len(event.text) + sum(len(file_path) for file_path in event.files) + 32
        if events and used_chars + event_size > char_budget:
            truncated = True
            return
        events.append(event)
        used_chars += event_size

    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            if should_filter_message_for_export(message):
                continue

            role = str(message.get("role", "unknown")).lower()
            parts = message.get("parts", [])
            if role != "tool" and isinstance(parts, list):
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    part_type = str(part.get("type", ""))
                    if part_type == "tool":
                        tool_name = str(part.get("tool") or part.get("name") or part.get("title") or "tool").strip()
                        _append_event(
                            _build_collect_event(
                                "tool_call",
                                role,
                                _extract_part_text(part),
                                tool_name=tool_name or "tool",
                            )
                        )
                        continue

                    part_text = _extract_part_text(part)
                    kind = _classify_text_event(role, part_text)
                    if kind is not None:
                        _append_event(_build_collect_event(kind, role, part_text))

            content_parts = get_text_content_parts(message)
            if role != "tool" and not parts and content_parts:
                for content in content_parts:
                    kind = _classify_text_event(role, content)
                    if kind is not None:
                        _append_event(_build_collect_event(kind, role, content))

            if role == "tool":
                tool_call_id = str(message.get("tool_call_id", "")).strip()
                content = "\n".join(content_parts) if content_parts else json.dumps(message, ensure_ascii=False)
                label = f"{tool_call_id}: {content}" if tool_call_id else content
                kind = _classify_text_event(role, label)
                if kind is not None:
                    _append_event(_build_collect_event(kind, role, label))

    if not events:
        fallback = _normalize_text(fallback_text)
        _append_event(_build_collect_event("fallback", "system", fallback or "(empty session)"))

    return tuple(events), truncated


def _render_event(event: CollectEvent) -> str:
    prefix = f"[{event.kind}] role={event.role}"
    if event.tool_name:
        prefix += f" tool={event.tool_name}"
    if event.files:
        prefix += f" files={','.join(event.files)}"
    return f"{prefix} text={event.text}"


def chunk_collect_events(
    events: Iterable[CollectEvent],
    *,
    target_chars: int = CHUNK_TARGET_CHARS,
) -> list[tuple[CollectEvent, ...]]:
    """Chunk events by approximate serialized size."""
    chunks: list[list[CollectEvent]] = []
    current: list[CollectEvent] = []
    current_size = 0

    for event in events:
        event_text = _render_event(event)
        event_size = len(event_text) + 1
        if current and current_size + event_size > target_chars:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(event)
        current_size += event_size

    if current:
        chunks.append(current)

    if not chunks:
        empty_chunk: tuple[CollectEvent, ...] = ()
        return [empty_chunk]

    return [tuple(chunk) for chunk in chunks]


def collect_entries(
    *,
    agents: list[BaseAgent],
    since_date: date,
    until_date: date,
    collect_config: CollectConfig | None = None,
    query_spec: QuerySpec | None = None,
    render_session_text_fn,
    local_tz: tzinfo | None = None,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
) -> tuple[list[CollectEntry], bool]:
    """Collect session entries for range."""
    entries: list[CollectEntry] = []
    has_truncated = False
    resolved_local_tz = local_tz or get_local_timezone()
    resolved_collect_config = collect_config or CollectConfig()
    matched_sessions: list[tuple[BaseAgent, Session, date]] = []

    for agent in agents:
        days_span = max((get_local_today(resolved_local_tz) - since_date).days + 1, 1)
        sessions = agent.get_sessions(days=days_span)
        deny_paths = resolved_collect_config.agent_denies.get(agent.name, ())
        if deny_paths:
            sessions = [session for session in sessions if not _is_session_denied(session, deny_paths)]
        if query_spec is not None:
            sessions = filter_sessions_by_query(agent, sessions, query_spec)

        for session in sessions:
            session_date = _session_local_date(session, resolved_local_tz)
            if session_date < since_date or session_date > until_date:
                continue
            matched_sessions.append((agent, session, session_date))

    total = len(matched_sessions)
    emit_collect_progress(
        progress_callback,
        stage="scan_sessions",
        current=0,
        total=total,
        message="scan sessions",
    )

    for index, (agent, session, session_date) in enumerate(matched_sessions, start=1):
        session_data = agent.get_session_data(session)
        uri = agent.get_session_uri(session)
        fallback_text = render_session_text_fn(uri, session_data)
        events, truncated = extract_collect_events(session_data, fallback_text=fallback_text)
        has_truncated = has_truncated or truncated

        entries.append(
            CollectEntry(
                date_value=session_date,
                created_at=session.created_at,
                agent_name=agent.name,
                agent_display_name=agent.display_name,
                session_id=session.id,
                session_title=session.title,
                session_uri=uri,
                project_directory=str(session.metadata.get("cwd") or session.metadata.get("directory") or ""),
                events=events,
                is_truncated=truncated,
            )
        )
        emit_collect_progress(
            progress_callback,
            stage="scan_sessions",
            current=index,
            total=total,
            message="scan sessions",
            session_uri=uri,
        )

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
        stage="plan_chunks",
        current=0,
        total=total,
        message="plan chunks",
    )

    for index, entry in enumerate(entries, start=1):
        chunks = tuple(chunk_collect_events(entry.events))
        total_chunks += len(chunks)
        planned_entries.append(PlannedCollectEntry(collect_entry=entry, chunks=chunks))
        emit_collect_progress(
            progress_callback,
            stage="plan_chunks",
            current=index,
            total=total,
            message="plan chunks",
            session_uri=entry.session_uri,
            chunk_total=total_chunks,
        )

    return planned_entries, total_chunks


def build_collect_chunk_prompt(
    entry: CollectEntry,
    chunk_events: tuple[CollectEvent, ...],
    *,
    chunk_index: int,
    chunk_total: int,
    local_tz: tzinfo | None = None,
) -> str:
    """Build prompt for a chunk-level structured summary."""
    resolved_local_tz = local_tz or get_local_timezone()
    lines = [
        "你是一个严谨的工作记录结构化摘要助手。",
        "请只基于给定 chunk 内容输出 JSON 对象，不要输出 Markdown，不要补充解释。",
        f"JSON 必须只包含这些字段: {', '.join(SUMMARY_FIELDS)}。",
        "每个字段都必须是字符串数组；没有内容时返回空数组。",
        "要求：",
        "1. 只保留事实，不要编造。",
        "2. 同一事实不要换说法重复写。",
        "3. errors 只放错误/异常/失败。",
        "4. files 只放文件路径。",
        "5. tools_used 只放工具名。",
        "",
        "会话元信息：",
        f"- session_uri: {entry.session_uri}",
        f"- title: {entry.session_title}",
        f"- project_directory: {entry.project_directory or '(unknown)'}",
        f"- created_at: {to_local_datetime(entry.created_at, resolved_local_tz).isoformat()}",
        f"- chunk: {chunk_index + 1}/{chunk_total}",
        "",
        "chunk events:",
    ]
    lines.extend(f"- {_render_event(event)}" for event in chunk_events)
    return "\n".join(lines)


def build_collect_merge_prompt(
    *,
    entry: CollectEntry,
    payloads: list[dict[str, list[str]]],
    merge_label: str,
) -> str:
    """Build prompt for session/group structured merge when deterministic merge is too large."""
    lines = [
        "你是一个严谨的结构化摘要归并助手。",
        "请把下面多个 JSON 摘要归并成一个 JSON 对象。",
        f"输出 JSON 仍然只能包含这些字段: {', '.join(SUMMARY_FIELDS)}。",
        "每个字段必须是字符串数组；没有内容时返回空数组。",
        "要求：去重、保留关键事实、压缩重复表述，不要输出字段之外的内容。",
        "",
        "上下文：",
        f"- merge_label: {merge_label}",
        f"- session_uri: {entry.session_uri}",
        "",
        "待归并摘要：",
    ]
    for index, payload in enumerate(payloads, start=1):
        lines.append(f"## summary {index}")
        lines.append(_serialize_summary_payload(payload))
    return "\n".join(lines)


def request_summary_from_llm(config: AIConfig, prompt: str, *, timeout_seconds: int = 90) -> str:
    """Call provider API and return markdown summary."""
    return _request_summary_from_llm(config, prompt, timeout_seconds=timeout_seconds)


def request_structured_summary_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    context_label: str,
    timeout_seconds: int = 90,
    retry_count: int = SUMMARY_PARSE_RETRY_COUNT,
    logger: CollectLogger | None = None,
    phase: str = "structured_summary",
    session_uri: str | None = None,
    chunk_index: int | None = None,
    chunk_total: int | None = None,
) -> dict[str, list[str]]:
    """Call LLM and parse one structured summary payload."""
    attempts = retry_count + 1
    last_error: Exception | None = None
    last_error_kind = "parse"
    for _ in range(attempts):
        request_id = str(uuid4())
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
                prompt_chars=len(prompt),
            )
        try:
            response = request_structured_summary_payload_from_llm(config, prompt, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            last_error_kind = "request"
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
                )
            continue
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
            )
        try:
            return normalize_summary_payload(_extract_json_object(response))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            last_error_kind = "parse"
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
                    response_preview=_truncate_log_preview(response),
                )
    if last_error_kind == "request":
        raise RuntimeError(f"{context_label}: structured summary request failed: {last_error}") from last_error
    raise RuntimeError(f"{context_label}: invalid structured summary response: {last_error}") from last_error


def request_structured_summary_payload_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int = 90,
) -> str:
    """Call provider API and return one structured summary payload string."""
    return _request_structured_summary_payload_from_llm(config, prompt, timeout_seconds=timeout_seconds)


def build_collect_session_prompt(
    entry: CollectEntry,
    *,
    source_truncated: bool,
    local_tz: tzinfo | None = None,
) -> str:
    """Build compatibility prompt string for one whole session."""
    chunks = chunk_collect_events(entry.events)
    return build_collect_chunk_prompt(
        entry,
        chunks[0],
        chunk_index=0,
        chunk_total=len(chunks),
        local_tz=local_tz,
    ) + ("\n\n注意：原始 session 内容在事件提取阶段已截断。" if source_truncated else "")


def _summarize_collect_entry(
    *,
    config: AIConfig,
    planned_entry: PlannedCollectEntry,
    index: int,
    timeout_seconds: int,
    local_tz: tzinfo | None,
    on_chunk_summarized: Callable[[CollectProgressEvent], None] | None = None,
    on_session_merged: Callable[[CollectProgressEvent], None] | None = None,
    logger: CollectLogger | None = None,
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
        )
        chunk_payloads.append(payload)
        emit_collect_progress(
            on_chunk_summarized,
            stage="summarize_chunks",
            current=1,
            total=1,
            message="summarize chunk",
            session_uri=entry.session_uri,
            chunk_index=chunk_index + 1,
            chunk_total=len(chunks),
        )

    merged = merge_summary_payloads(chunk_payloads)
    if len(chunk_payloads) > 1 and _summary_payload_size(merged) > SESSION_MERGE_LLM_THRESHOLD:
        merged = request_structured_summary_from_llm(
            config,
            build_collect_merge_prompt(entry=entry, payloads=chunk_payloads, merge_label="session"),
            context_label=f"{entry.session_uri} session merge",
            timeout_seconds=timeout_seconds,
            logger=logger,
            phase="session_merge",
            session_uri=entry.session_uri,
            chunk_total=len(chunks),
        )
    emit_collect_progress(
        on_session_merged,
        stage="merge_sessions",
        current=1,
        total=1,
        message="merge session",
        session_uri=entry.session_uri,
        chunk_total=len(chunks),
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

    emit_collect_progress(
        progress_callback,
        stage="summarize_chunks",
        current=0,
        total=total_chunks,
        message="summarize chunks",
        concurrency=max_workers,
    )
    emit_collect_progress(
        progress_callback,
        stage="merge_sessions",
        current=0,
        total=total,
        message="merge sessions",
    )

    def _mark_chunk_summarized(event: CollectProgressEvent) -> None:
        nonlocal summarized_chunks
        with chunk_progress_lock:
            summarized_chunks += event.current
            current = summarized_chunks
        emit_collect_progress(
            progress_callback,
            stage="summarize_chunks",
            current=current,
            total=total_chunks,
            message="summarize chunks",
            session_uri=event.session_uri,
            chunk_index=event.chunk_index,
            chunk_total=event.chunk_total,
            concurrency=max_workers,
        )

    def _mark_session_merged(event: CollectProgressEvent) -> None:
        nonlocal merged_sessions
        with merge_progress_lock:
            merged_sessions += event.current
            current = merged_sessions
        emit_collect_progress(
            progress_callback,
            stage="merge_sessions",
            current=current,
            total=total,
            message="merge sessions",
            session_uri=event.session_uri,
            chunk_total=event.chunk_total,
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
                result = future.result()
                results[index] = result

                try:
                    next_index, next_entry = next(pending_entries)
                except StopIteration:
                    continue
                future_to_index[executor.submit(_summarize, next_index, next_entry)] = next_index

    return [item for item in results if item is not None]


def _build_summary_bucket_lines(
    session_summaries: list[SessionSummaryEntry],
    *,
    key_fn: Callable[[SessionSummaryEntry], str],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for summary in session_summaries:
        key = key_fn(summary)
        payload = summary.summary_data
        highlights = payload["key_actions"][:2] + payload["decisions"][:1] + payload["errors"][:1]
        line = f"{summary.collect_entry.session_title}: {'; '.join(_dedupe_preserve_order(highlights, limit=4)) or '(no highlights)'}"
        grouped[key].append(line)
    return {key: _dedupe_preserve_order(values, limit=6) for key, values in grouped.items()}


def reduce_collect_summaries(
    *,
    config: AIConfig,
    session_summaries: list[SessionSummaryEntry],
    timeout_seconds: int = 90,
    group_size: int = GROUP_SIZE,
    progress_callback: Callable[[CollectProgressEvent], None] | None = None,
    logger: CollectLogger | None = None,
) -> CollectAggregate:
    """Reduce per-session summaries via tree reduction into one final aggregate."""
    if not session_summaries:
        return CollectAggregate(
            summary_data=empty_summary_payload(),
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
            stage="tree_reduction",
            current=0,
            total=total_groups,
            message="tree reduction",
            level=reduction_depth,
        )
        for start in range(0, len(working), group_size):
            group = working[start : start + group_size]
            payloads = [item.summary_data for item in group]
            merged = merge_summary_payloads(payloads)
            if _summary_payload_size(merged) > SESSION_MERGE_LLM_THRESHOLD:
                dummy_entry = session_summaries[min(start, len(session_summaries) - 1)].collect_entry
                merged = request_structured_summary_from_llm(
                    config,
                    build_collect_merge_prompt(
                        entry=dummy_entry, payloads=payloads, merge_label=f"group-level-{reduction_depth}"
                    ),
                    context_label=f"group merge level {reduction_depth} index {start // group_size + 1}",
                    timeout_seconds=timeout_seconds,
                    logger=logger,
                    phase="group_merge",
                    session_uri=dummy_entry.session_uri,
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
                stage="tree_reduction",
                current=(start // group_size) + 1,
                total=total_groups,
                message="tree reduction",
                level=reduction_depth,
            )
        working = next_level

    date_summaries = _build_summary_bucket_lines(
        session_summaries,
        key_fn=lambda item: item.collect_entry.date_value.isoformat(),
    )
    project_summaries = _build_summary_bucket_lines(
        session_summaries,
        key_fn=lambda item: item.collect_entry.project_directory or "(unknown)",
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
) -> str:
    """Build final collect markdown prompt from the final aggregate."""
    lines = [
        "你是一个工作记录分析助手。",
        "请基于给定的结构化聚合数据输出 Markdown，总结重点工作。",
        "必须严格使用以下结构：",
        f"# 时段工作总结（{since_date.isoformat()} ~ {until_date.isoformat()}）",
        "## 按日期",
        "## 按项目/目录",
        "## 重点事项（决策/风险/阻塞）",
        "## 产出清单",
        "## 下一步建议",
        "要求：避免空话，按事实归纳；同一事项合并去重；可按优先级标注。",
        "",
        f"- session_count: {aggregate.session_count}",
        f"- reduction_depth: {aggregate.reduction_depth}",
    ]
    if has_truncated:
        lines.append("注意：部分 session 在事件提取阶段达到预算上限，最终结论可能遗漏低优先级细节。")

    lines.extend(
        [
            "",
            "聚合摘要 JSON：",
            _serialize_summary_payload(aggregate.summary_data),
            "",
            "按日期摘要：",
        ]
    )
    for bucket, values in aggregate.date_summaries.items():
        lines.append(f"### {bucket}")
        lines.extend(f"- {value}" for value in values)

    lines.extend(["", "按项目/目录摘要："])
    for bucket, values in aggregate.project_summaries.items():
        lines.append(f"### {bucket}")
        lines.extend(f"- {value}" for value in values)

    return "\n".join(lines)


def write_collect_markdown(
    markdown: str,
    *,
    since_date: date,
    until_date: date,
    output_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write collect markdown file to current directory or a specific path."""
    if output_path is not None and output_dir is not None:
        raise ValueError("output_path and output_dir are mutually exclusive")

    if output_path is not None:
        path = output_path
    else:
        base = output_dir if output_dir is not None else Path.cwd()
        path = base / f"agent-dump-collect-{since_date.strftime('%Y%m%d')}-{until_date.strftime('%Y%m%d')}.md"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path
