"""Shared models and constants for collect mode."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import ClassVar

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
INSIGHT_SUMMARY_FIELDS = ("scene", "stuck", "turning")


class CollectMode(str, Enum):
    PM = "pm"
    INSIGHT = "insight"

    def __str__(self) -> str:
        return self.value


class CollectStage(str, Enum):
    COLLECT_START = "collect_start"
    COLLECT_OVERVIEW = "collect_overview"
    SCAN_SESSIONS = "scan_sessions"
    PLAN_CHUNKS = "plan_chunks"
    SUMMARIZE_CHUNKS = "summarize_chunks"
    MERGE_SESSIONS = "merge_sessions"
    TREE_REDUCTION = "tree_reduction"
    RENDER_FINAL = "render_final"
    WRITE_OUTPUT = "write_output"


class CollectFailurePhase(str, Enum):
    READ = "read"
    SUMMARIZE = "summarize"
    RENDER = "render"
    WRITE = "write"


_COLLECT_MODE_FIELDS = {
    CollectMode.PM: SUMMARY_FIELDS,
    CollectMode.INSIGHT: INSIGHT_SUMMARY_FIELDS,
}


def collect_fields_for(mode: CollectMode) -> tuple[str, ...]:
    """Return the summary field names for the given collect mode."""
    return _COLLECT_MODE_FIELDS[mode]


EVENT_EXTRACT_CHAR_BUDGET = 12000
CHUNK_TARGET_CHARS = 3200
GROUP_SIZE = 8
MAX_SUMMARY_ITEMS_PER_FIELD = 12
SESSION_MERGE_LLM_THRESHOLD = 48
SUMMARY_PARSE_RETRY_COUNT = 1
SUMMARY_TRANSPORT_RETRY_COUNT = 1
MAX_LOG_PREVIEW_CHARS = 400


@dataclass(frozen=True)
class CollectEvent:
    """One extracted high-signal event from a session."""

    kind: str
    role: str
    text: str
    files: tuple[str, ...] = ()


class CollectProgressEvent:
    """Base type for the closed set of collect progress events."""

    stage: ClassVar[CollectStage]


@dataclass(frozen=True)
class CollectStartProgress(CollectProgressEvent):
    since: str
    until: str

    stage: ClassVar[CollectStage] = CollectStage.COLLECT_START


@dataclass(frozen=True)
class CollectOverviewProgress(CollectProgressEvent):
    session_count: int
    chunk_count: int
    concurrency: int
    agent_session_counts: dict[str, int]

    stage: ClassVar[CollectStage] = CollectStage.COLLECT_OVERVIEW


@dataclass(frozen=True)
class ScanSessionsProgress(CollectProgressEvent):
    current: int
    total: int
    session_uri: str | None = None

    stage: ClassVar[CollectStage] = CollectStage.SCAN_SESSIONS


@dataclass(frozen=True)
class PlanChunksProgress(CollectProgressEvent):
    current: int
    total: int
    chunk_total: int = 0
    session_uri: str | None = None

    stage: ClassVar[CollectStage] = CollectStage.PLAN_CHUNKS


@dataclass(frozen=True)
class SummarizeChunksProgress(CollectProgressEvent):
    current: int
    total: int
    concurrency: int
    session_uri: str | None = None
    chunk_index: int | None = None
    chunk_total: int | None = None

    stage: ClassVar[CollectStage] = CollectStage.SUMMARIZE_CHUNKS


@dataclass(frozen=True)
class MergeSessionsProgress(CollectProgressEvent):
    current: int
    total: int
    session_uri: str | None = None
    chunk_total: int | None = None

    stage: ClassVar[CollectStage] = CollectStage.MERGE_SESSIONS


@dataclass(frozen=True)
class TreeReductionProgress(CollectProgressEvent):
    level: int
    current: int
    total: int

    stage: ClassVar[CollectStage] = CollectStage.TREE_REDUCTION


@dataclass(frozen=True)
class RenderFinalProgress(CollectProgressEvent):
    current: int
    total: int

    stage: ClassVar[CollectStage] = CollectStage.RENDER_FINAL


@dataclass(frozen=True)
class WriteOutputProgress(CollectProgressEvent):
    current: int
    total: int

    stage: ClassVar[CollectStage] = CollectStage.WRITE_OUTPUT


@dataclass
class CollectRunStats:
    """User-facing collect workload stats."""

    since: str
    until: str
    agent_session_counts: dict[str, int]
    session_count: int
    chunk_count: int
    concurrency: int


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


@dataclass
class SessionSummaryEntry:
    """One summarized session entry for collect aggregation."""

    collect_entry: CollectEntry
    summary_data: dict[str, list[str]]


@dataclass
class GroupSummaryEntry:
    """Intermediate group summary used by tree reduction."""

    summary_data: dict[str, list[str]]
    session_count: int


@dataclass
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
