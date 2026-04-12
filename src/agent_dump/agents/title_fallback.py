"""
Internal helpers for session title fallback.
"""

from pathlib import Path
import re

TITLE_MAX_LENGTH = 100
UNTITLED_SESSION = "Untitled Session"
_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_title_text(text: str) -> str | None:
    """Normalize extracted title text for display."""
    cleaned = _WHITESPACE_PATTERN.sub(" ", text).strip()
    if not cleaned:
        return None
    return cleaned[:TITLE_MAX_LENGTH]


def basename_title(path_value: str | Path | None) -> str | None:
    """Return a stable basename for fallback title."""
    if path_value is None:
        return None

    raw = str(path_value).strip()
    if not raw:
        return None

    normalized = raw.rstrip("/\\")
    if not normalized:
        return None

    name = Path(normalized).name.strip()
    if name:
        return name

    return None


def resolve_session_title(
    explicit_title: str | None,
    message_title: str | None,
    directory_title: str | None,
) -> str:
    """Resolve final session title from explicit, message, and directory fallbacks."""
    for candidate in (explicit_title, message_title, directory_title):
        normalized = normalize_title_text(candidate) if candidate is not None else None
        if normalized:
            return normalized
    return UNTITLED_SESSION
