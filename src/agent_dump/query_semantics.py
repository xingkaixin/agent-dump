"""Literal text semantics shared by Query, Search, and their adapters."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any

from agent_dump.transcript import read_messages


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


def extract_transcript_searchable_text(session_data: Mapping[str, Any]) -> str | None:
    if not isinstance(session_data.get("messages"), list):
        return None

    text_parts: list[str] = []
    for transcript_message in read_messages(session_data):
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
class TextQueryMatch:
    """Evidence produced by one normalized scan of a field collection."""

    snippet: str
    fully_matching_field_indexes: frozenset[int]


@dataclass(frozen=True)
class _TextQueryEvaluation:
    normalized_fields: tuple[tuple[int, str], ...]
    literal_spans: tuple[tuple[tuple[int, int] | None, ...], ...]


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
        return self._evaluate(fields) is not None

    def has_evidence(self, text: str) -> bool:
        normalized = normalize_search_text(text.replace("**", ""))
        return any(_find_literal(normalized, literal) is not None for literal in self.literals)

    def find_match(self, fields: tuple[str, ...] | list[str], context_chars: int = 48) -> TextQueryMatch | None:
        evaluation = self._evaluate(fields)
        if evaluation is None:
            return None

        ranked_fields = sorted(
            zip(evaluation.normalized_fields, evaluation.literal_spans, strict=True),
            key=lambda item: sum(span is not None for span in item[1]),
            reverse=True,
        )
        fully_matching_field_indexes = frozenset(
            field_index
            for ((field_index, _), spans) in zip(
                evaluation.normalized_fields,
                evaluation.literal_spans,
                strict=True,
            )
            if all(span is not None for span in spans)
        )
        for literal_index in range(len(self.literals)):
            for (_, normalized), spans in ranked_fields:
                span = spans[literal_index]
                if span is None:
                    continue
                match_start, match_end = span
                start = max(0, match_start - context_chars)
                end = min(len(normalized), match_end + context_chars)
                prefix = "..." if start > 0 else ""
                suffix = "..." if end < len(normalized) else ""
                return TextQueryMatch(
                    snippet=(
                        prefix
                        + normalized[start:match_start]
                        + "**"
                        + normalized[match_start:match_end]
                        + "**"
                        + normalized[match_end:end]
                        + suffix
                    ),
                    fully_matching_field_indexes=fully_matching_field_indexes,
                )
        return None

    def build_snippet(self, fields: tuple[str, ...] | list[str], context_chars: int = 48) -> str | None:
        match = self.find_match(fields, context_chars=context_chars)
        return match.snippet if match is not None else None

    def _evaluate(self, fields: tuple[str, ...] | list[str]) -> _TextQueryEvaluation | None:
        normalized_fields = tuple(
            (field_index, normalize_search_text(field)) for field_index, field in enumerate(fields) if field
        )
        if not self.literals or not normalized_fields:
            return None

        literal_spans = tuple(
            tuple(_find_literal(normalized, literal) for literal in self.literals)
            for _, normalized in normalized_fields
        )
        if self.mode is TextQueryMode.KEYWORD:
            matched = any(spans[0] is not None for spans in literal_spans)
        else:
            matched = all(
                any(spans[index] is not None for spans in literal_spans) for index in range(len(self.literals))
            )
        if not matched:
            return None
        return _TextQueryEvaluation(normalized_fields=normalized_fields, literal_spans=literal_spans)
