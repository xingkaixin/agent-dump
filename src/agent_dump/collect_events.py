"""Visible dialogue extraction and chunking for collect mode."""

from collections.abc import Iterable, Mapping
import re
from typing import Any

from agent_dump.collect_models import CHUNK_TARGET_CHARS, EVENT_EXTRACT_CHAR_BUDGET, CollectEvent
from agent_dump.collect_summary import normalize_text
from agent_dump.message_filter import should_filter_message_for_export
from agent_dump.transcript import read_messages

IGNORABLE_DIALOGUE_PATTERN = re.compile(
    r"(?:hi|hello|thanks|thank you|你好|您好|好的|收到|明白|嗯嗯|ok|okay)[!！,.，。?？\s]*",
    re.IGNORECASE,
)
EVENT_KIND_BY_ROLE = {"user": "user_message", "assistant": "agent_message"}


def extract_collect_events(
    session_data: Mapping[str, Any],
    *,
    char_budget: int = EVENT_EXTRACT_CHAR_BUDGET,
) -> tuple[tuple[CollectEvent, ...], bool]:
    """Extract visible user and agent messages from one normalized session."""
    events: list[CollectEvent] = []
    used_chars = 0
    for transcript_message in read_messages(session_data):
        if should_filter_message_for_export(transcript_message.raw):
            continue

        role = transcript_message.role
        if role not in EVENT_KIND_BY_ROLE:
            continue

        seen_texts: set[str] = set()
        for part_text in transcript_message.visible_texts:
            normalized = normalize_text(part_text)
            identity = normalized.casefold()
            if not normalized or identity in seen_texts or IGNORABLE_DIALOGUE_PATTERN.fullmatch(normalized):
                continue
            seen_texts.add(identity)
            event = CollectEvent(kind=EVENT_KIND_BY_ROLE[role], role=role, text=normalized)
            event_size = len(render_collect_event(event)) + 1
            if used_chars + event_size > char_budget:
                remaining = char_budget - used_chars - (event_size - len(normalized))
                if remaining > 0:
                    events.append(CollectEvent(kind=event.kind, role=role, text=normalized[:remaining]))
                return tuple(events), True
            events.append(event)
            used_chars += event_size

    return tuple(events), False


def render_collect_event(event: CollectEvent) -> str:
    """Serialize one collect event for an LLM data envelope."""
    return f"[{event.kind}] role={event.role} text={event.text}"


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
