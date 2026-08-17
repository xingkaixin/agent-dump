"""
Base agent handler interface
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any

from agent_dump.diagnostics import source_missing, unsupported_capability
from agent_dump.export_paths import build_session_output_path
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot
from agent_dump.private_files import copy_private_file, ensure_output_dir, write_private_text
from agent_dump.session_data import SessionDataCache
from agent_dump.time_utils import to_local_datetime


@dataclass
class Session:
    """Unified session data model"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    source_path: Path
    metadata: dict[str, Any]


class MessageCountCompleteness(str, Enum):
    EXACT = "exact"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MessageCountFact:
    """One message count with explicit evidence completeness."""

    value: int | None
    completeness: MessageCountCompleteness

    def __post_init__(self) -> None:
        valid_count = isinstance(self.value, int) and not isinstance(self.value, bool) and self.value >= 0
        if self.completeness is MessageCountCompleteness.EXACT and not valid_count:
            raise ValueError("exact message count requires a non-negative integer")
        if self.completeness is MessageCountCompleteness.UNKNOWN and self.value is not None:
            raise ValueError("unknown message count cannot carry a value")

    @property
    def exact_value(self) -> int:
        if self.completeness is not MessageCountCompleteness.EXACT or self.value is None:
            raise ValueError("message count is not exact")
        return self.value

    @classmethod
    def from_provider_value(cls, value: Any) -> "MessageCountFact":
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return cls(value=value, completeness=MessageCountCompleteness.EXACT)
        return cls(value=None, completeness=MessageCountCompleteness.UNKNOWN)


@dataclass(frozen=True)
class SessionFacts:
    """Stable cross-provider facts derived from one Session."""

    working_directory: Path | None
    provider_project: str | None
    session_source: Path
    change_sources: tuple[Path, ...]
    message_count: MessageCountFact

    @property
    def display_location(self) -> str:
        if self.working_directory is not None:
            return str(self.working_directory)
        if self.provider_project is not None:
            return self.provider_project
        source = self.session_source
        return str(source.parent if source.is_file() else source)


def derive_session_facts(
    session: Session,
    *,
    change_sources: tuple[Path, ...] = (),
) -> SessionFacts:
    """Derive stable facts from the canonical metadata populated by a provider."""
    metadata = session.metadata
    return SessionFacts(
        working_directory=_metadata_path(metadata.get("cwd") or metadata.get("directory")),
        provider_project=_metadata_text(metadata.get("project")),
        session_source=session.source_path,
        change_sources=tuple(dict.fromkeys(change_sources)),
        message_count=MessageCountFact.from_provider_value(metadata.get("message_count")),
    )


class BaseAgent(ABC):
    """Abstract base class for agent handlers"""

    #: URI 模式下该 provider 不支持的导出格式
    unsupported_uri_formats: frozenset[str] = frozenset()
    raw_export_suffix: str = ".raw.jsonl"

    def __init__(self, name: str, display_name: str):
        self.name = name
        self.display_name = display_name
        self._session_data_cache = SessionDataCache()

    @abstractmethod
    def scan(self) -> list[Session]:
        """
        Scan for available sessions.
        Returns list of sessions found.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this agent tool is installed and has sessions.
        """
        pass

    @abstractmethod
    def get_sessions(self, days: int = 7) -> list[Session]:
        """
        Get sessions from the last N days.
        """
        pass

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON. Returns the exported file path."""
        payload = self._json_export_payload(session)
        ensure_output_dir(output_dir)
        output_path = self._build_output_path(session, output_dir, ".json")
        return write_private_text(output_path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _json_export_payload(self, session: Session) -> dict[str, Any]:
        """Data to serialize for JSON export.

        走请求级缓存，同一条命令里 print/markdown/search 已经解析过的会话不再重解析。
        需要做导出专属变换的 provider 覆盖此方法，并且必须先浅拷贝——缓存返回的是
        共享可变 dict，直接改键会污染其他消费者看到的同一份数据。
        """
        return self.get_cached_session_data(session)

    def get_formatted_title(self, session: Session) -> str:
        """Get formatted title for display"""
        title = session.title[:60] + "..." if len(session.title) > 60 else session.title
        time_str = to_local_datetime(session.created_at).strftime("%Y-%m-%d %H:%M")
        return f"{title} ({time_str})"

    def get_session_uri(self, session: Session) -> str:
        """Get the agent session URI for a session"""
        return f"{self.name}://{session.id}"

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Find one session by id.

        Default implementation scans all sessions; providers should override
        with a direct lookup when their storage supports it.
        """
        for session in self.get_sessions(days=3650):
            if session.id == session_id:
                return session
        return None

    def filter_sessions_by_keyword(self, sessions: list[Session], keyword: str) -> list[Session] | None:
        """Match one normalized literal phrase against the logical session corpus.

        A provider storage fallback must return the same hit set as the shared title
        and transcript matcher. It runs only when the persistent index is unavailable;
        return None when storage cannot express that contract.
        """
        del sessions, keyword
        return None

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        """Return provider roots checked during discovery."""
        return ()

    def get_session_change_sources(self, session: Session) -> tuple[Path, ...]:
        """Return provider-owned per-session sources that can invalidate cached data."""
        del session
        return ()

    def get_session_facts(self, session: Session) -> SessionFacts:
        """Map provider metadata to the stable facts shared workflows consume."""
        return derive_session_facts(
            session,
            change_sources=self.get_session_change_sources(session),
        )

    def get_session_head(self, session: Session) -> dict[str, Any]:
        """Get lightweight discovery metadata for one session."""
        metadata = session.metadata
        facts = self.get_session_facts(session)

        return {
            "uri": self.get_session_uri(session),
            "agent": self.display_name,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "cwd_or_project": facts.display_location,
            "model": metadata.get("model") or metadata.get("model_provider"),
            "message_count": facts.message_count.value,
            "message_count_completeness": facts.message_count.completeness.value,
            "subtargets": [],
        }

    def get_session_summary_fields(self, session: Session) -> dict[str, str | int | None]:
        """Return reduced metadata fields for list/selector display."""
        facts = self.get_session_facts(session)
        model = session.metadata.get("model")
        branch = session.metadata.get("branch")

        return {
            "cwd_project": facts.display_location,
            "model": str(model) if isinstance(model, str) and model.strip() else None,
            "branch": str(branch) if isinstance(branch, str) and branch.strip() else None,
            "message_count": facts.message_count.value,
            "message_count_completeness": facts.message_count.completeness.value,
            "updated_at": to_local_datetime(session.updated_at).strftime("%Y-%m-%d %H:%M"),
        }

    def _build_output_path(self, session: Session, output_dir: Path, suffix: str) -> Path:
        """Build a safe output path for a session export."""
        return build_session_output_path(output_dir, session.id, suffix)

    def _build_raw_output_path(self, session: Session, output_dir: Path) -> Path:
        """Build output path for raw session export."""
        return self._build_output_path(session, output_dir, self.raw_export_suffix)

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        """Export the original session file when one exists."""
        source_path = session.source_path
        if not source_path.exists():
            raise source_missing(
                "raw session source is missing",
                missing_path=source_path,
                searched_roots=[root.render() for root in self.get_search_roots()],
                next_steps=(
                    i18n.t(Keys.DIAG_STEP_RAW_SOURCE_LOCAL),
                    i18n.t(Keys.DIAG_STEP_LIST_TO_CHECK_VISIBLE),
                ),
            )
        if not source_path.is_file():
            raise unsupported_capability(
                "raw export is not supported for this session source",
                capability_gap="session source is a directory, not a single raw file",
                details=(f"source path: {source_path}",),
                next_steps=(
                    i18n.t(Keys.DIAG_STEP_USE_JSON_OR_MARKDOWN),
                    i18n.t(Keys.DIAG_STEP_CHECK_PROVIDER_HAS_RAW),
                ),
            )

        ensure_output_dir(output_dir)
        output_path = self._build_raw_output_path(session, output_dir)
        return copy_private_file(source_path, output_path)

    @abstractmethod
    def get_session_data(self, session: Session) -> dict:
        """
        Get session data as a dictionary.
        Returns dict with keys: id, title, messages, etc.
        """
        pass

    def get_cached_session_data(self, session: Session) -> dict[str, Any]:
        """Get session data once per change signal for this agent instance."""
        return self._session_data_cache.get(self, session)

    @contextmanager
    def lease_cached_session_data(self, session: Session) -> Iterator[dict[str, Any]]:
        """Keep parsed data only while one bulk consumer derives its smaller output."""
        with self._session_data_cache.lease(self, session) as session_data:
            yield session_data


def _metadata_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _metadata_path(value: Any) -> Path | None:
    text = _metadata_text(value)
    return Path(text) if text is not None else None
