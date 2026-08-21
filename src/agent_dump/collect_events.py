"""Deterministic event extraction and chunking for collect mode."""

from collections.abc import Callable, Iterable, Mapping
import re
from typing import Any

from agent_dump.collect_models import CHUNK_TARGET_CHARS, EVENT_EXTRACT_CHAR_BUDGET, CollectEvent
from agent_dump.collect_summary import dedupe_preserve_order, normalize_text
from agent_dump.message_filter import should_filter_message_for_export
from agent_dump.transcript import read_messages

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


def _truncate_excerpt(text: str, limit: int = 280) -> str:
    normalized = text.strip()
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3].rstrip()}..."


def _find_paths_in_text(text: str) -> list[str]:
    candidates = [match.group(0).strip(".,:;)]}") for match in PATH_PATTERN.finditer(text)]
    return dedupe_preserve_order(candidates, limit=6)


def _build_collect_event(kind: str, role: str, text: str) -> CollectEvent | None:
    normalized_text = _truncate_excerpt(text)
    if not normalized_text:
        return None
    files = tuple(_find_paths_in_text(normalized_text))
    return CollectEvent(kind=kind, role=role, text=normalized_text, files=files)


def _classify_text_event(role: str, text: str) -> str | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    if GREETING_PATTERN.match(normalized) and len(normalized) <= 60:
        return None
    if role == "user":
        return "user_intent"
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
    session_data: Mapping[str, Any],
    *,
    fallback_text_fn: Callable[[], str] | None = None,
    char_budget: int = EVENT_EXTRACT_CHAR_BUDGET,
) -> tuple[tuple[CollectEvent, ...], bool]:
    """Extract deterministic high-signal events from one normalized session."""
    events: list[CollectEvent] = []
    used_chars = 0
    truncated = False

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

    for transcript_message in read_messages(session_data):
        if should_filter_message_for_export(transcript_message.raw):
            continue

        role = transcript_message.role
        if role not in {"user", "assistant"}:
            continue

        for part_text in transcript_message.texts:
            kind = _classify_text_event(role, part_text)
            if kind is not None:
                _append_event(_build_collect_event(kind, role, part_text))

    if not events:
        fallback = normalize_text(fallback_text_fn() if fallback_text_fn is not None else "")
        _append_event(_build_collect_event("fallback", "system", fallback or "(empty session)"))

    return tuple(events), truncated


def render_collect_event(event: CollectEvent) -> str:
    """Serialize one collect event for an LLM data envelope."""
    prefix = f"[{event.kind}] role={event.role}"
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
        event_size = len(render_collect_event(event)) + 1
        if current and current_size + event_size > target_chars:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(event)
        current_size += event_size

    if current:
        chunks.append(current)
    if not chunks:
        return [()]
    return [tuple(chunk) for chunk in chunks]
