"""Shared models and constants for collect mode."""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SUPPORTED_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d")
SUMMARY_FIELDS = (
    "topics",
    "decisions",
    "key_actions",
    "code_changes",
    "errors",
    "tools_used",
    "files",
    "artifacts",
    "open_questions",
    "notes",
)
EVENT_EXTRACT_CHAR_BUDGET = 12000
CHUNK_TARGET_CHARS = 3200
GROUP_SIZE = 8
MAX_SUMMARY_ITEMS_PER_FIELD = 12
SESSION_MERGE_LLM_THRESHOLD = 48
SUMMARY_PARSE_RETRY_COUNT = 1
MAX_LOG_PREVIEW_CHARS = 400


@dataclass(frozen=True)
class CollectEvent:
    """One extracted high-signal event from a session."""

    kind: str
    role: str
    text: str
    files: tuple[str, ...] = ()
    tool_name: str | None = None


@dataclass(frozen=True)
class CollectProgressEvent:
    """Structured progress event for collect mode."""

    stage: str
    current: int
    total: int
    message: str
    session_uri: str | None = None
    chunk_index: int | None = None
    chunk_total: int | None = None
    level: int | None = None


@dataclass(frozen=True)
class CollectEntry:
    """One collected session entry."""

    date_value: date
    created_at: datetime
    agent_name: str
    agent_display_name: str
    session_id: str
    session_title: str
    session_uri: str
    project_directory: str
    events: tuple[CollectEvent, ...]
    is_truncated: bool


@dataclass(frozen=True)
class SessionSummaryEntry:
    """One summarized session entry for collect aggregation."""

    index: int
    collect_entry: CollectEntry
    summary_data: dict[str, list[str]]
    chunk_count: int
    source_truncated: bool


@dataclass(frozen=True)
class GroupSummaryEntry:
    """Intermediate group summary used by tree reduction."""

    level: int
    summary_data: dict[str, list[str]]
    session_count: int


@dataclass(frozen=True)
class CollectAggregate:
    """Final aggregate input used to render the markdown report."""

    summary_data: dict[str, list[str]]
    date_summaries: dict[str, list[str]]
    project_summaries: dict[str, list[str]]
    session_count: int
    reduction_depth: int


@dataclass(frozen=True)
class PlannedCollectEntry:
    """One collect entry with deterministic chunk planning."""

    collect_entry: CollectEntry
    chunks: tuple[tuple[CollectEvent, ...], ...]


@dataclass(frozen=True)
class CollectLogger:
    """Append-only JSONL logger for collect diagnostics."""

    enabled: bool
    path: Path | None = None
    run_id: str | None = None

    def log(self, event: str, **payload: Any) -> None:
        if not self.enabled or self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now().astimezone().isoformat(),
                "event": event,
                "run_id": self.run_id,
                **payload,
            }
            with self.path.open("a", encoding="utf-8") as handle:
                import json

                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            return
