"""Literal text semantics shared by Query, Search, and their adapters."""

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any

from agent_dump.transcript import read_message


class TextQueryMode(Enum):
    """Closed set of user-visible text matching operations."""

    KEYWORD = "keyword"
    SEARCH_TERMS = "search-terms"


def normalize_search_text(text: str) -> str:
    """Collapse whitespace without changing display characters."""
    return " ".join(text.split())


def serialize_search_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def extract_transcript_searchable_text(session_data: dict[str, Any]) -> str | None:
    messages = session_data.get("messages")
    if not isinstance(messages, list):
        return None

    text_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        transcript_message = read_message(message)
        contents = list(transcript_message.searchable_texts)
        for call in transcript_message.tool_calls:
            if call.arguments is not None:
                contents.append(serialize_search_value(call.arguments))
            if call.output is not None:
                contents.append(serialize_search_value(call.output))
            if call.prompt:
                contents.append(call.prompt)
        text_parts.extend(content.strip() for content in contents if content and content.strip())

    return "\n\n".join(text_parts)


def _find_literal(text: str, literal: str) -> tuple[int, int] | None:
    match = re.search(re.escape(literal), text, flags=re.IGNORECASE)
    return match.span() if match is not None else None


@dataclass(frozen=True)
class TextQuery:
    """Parsed literal matching facts independent of any storage adapter."""

    mode: TextQueryMode
    literals: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str, mode: TextQueryMode) -> "TextQuery":
        normalized = normalize_search_text(raw)
        if not normalized:
            return cls(mode=mode, literals=())
        if mode is TextQueryMode.KEYWORD:
            return cls(mode=mode, literals=(normalized,))

        literals = tuple(dict.fromkeys(normalized.split(" ")))
        return cls(mode=mode, literals=literals)

    @property
    def is_empty(self) -> bool:
        return not self.literals

    def matches(self, fields: tuple[str, ...] | list[str]) -> bool:
        normalized_fields = tuple(normalize_search_text(field) for field in fields if field)
        if not self.literals or not normalized_fields:
            return False
        if self.mode is TextQueryMode.KEYWORD:
            literal = self.literals[0]
            return any(_find_literal(field, literal) is not None for field in normalized_fields)
        return all(
            any(_find_literal(field, literal) is not None for field in normalized_fields) for literal in self.literals
        )

    def has_evidence(self, text: str) -> bool:
        normalized = normalize_search_text(text.replace("**", ""))
        return any(_find_literal(normalized, literal) is not None for literal in self.literals)

    def build_snippet(self, fields: tuple[str, ...] | list[str], context_chars: int = 48) -> str | None:
        normalized_fields = [normalize_search_text(field) for field in fields if field]
        normalized_fields.sort(
            key=lambda field: sum(_find_literal(field, literal) is not None for literal in self.literals),
            reverse=True,
        )
        for literal in self.literals:
            for normalized in normalized_fields:
                match = _find_literal(normalized, literal)
                if match is None:
                    continue
                match_start, match_end = match
                start = max(0, match_start - context_chars)
                end = min(len(normalized), match_end + context_chars)
                prefix = "..." if start > 0 else ""
                suffix = "..." if end < len(normalized) else ""
                return (
                    prefix
                    + normalized[start:match_start]
                    + "**"
                    + normalized[match_start:match_end]
                    + "**"
                    + normalized[match_end:end]
                    + suffix
                )
        return None
