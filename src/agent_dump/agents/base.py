"""
Base agent handler interface
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, ClassVar

from agent_dump.export_paths import build_session_output_path
from agent_dump.paths import SearchRoot
from agent_dump.provider_diagnostics import ProviderDiagnostic, ProviderDiagnosticSink
from agent_dump.session_data import SessionDataCache
from agent_dump.session_exports import copy_raw_session_file, write_session_json
from agent_dump.session_projection import build_session_head, build_session_summary_fields, format_session_title


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

    provider_name: ClassVar[str] = ""
    provider_display_name: ClassVar[str] = ""

    #: URI 模式下该 provider 不支持的导出格式
    unsupported_uri_formats: frozenset[str] = frozenset()
    raw_export_suffix: str = ".raw.jsonl"

    def __init__(self, name: str | None = None, display_name: str | None = None) -> None:
        resolved_name = name if name is not None else type(self).provider_name
        resolved_display_name = display_name if display_name is not None else type(self).provider_display_name
        if not resolved_name or not resolved_display_name:
            raise ValueError("agent name and display name must be non-empty")
        self.name = resolved_name
        self.display_name = resolved_display_name
        self._session_data_cache = SessionDataCache()
        self._diagnostic_sink: ProviderDiagnosticSink | None = None
        self._diagnostic_scope_lock = RLock()

    @contextmanager
    def _use_diagnostic_sink(self, sink: ProviderDiagnosticSink | None) -> Iterator[None]:
        """Use one diagnostic destination for the duration of a provider operation."""
        with self._diagnostic_scope_lock:
            previous_sink = self._diagnostic_sink
            self._diagnostic_sink = sink
            try:
                yield
            finally:
                self._diagnostic_sink = previous_sink

    def _report_diagnostic(self, message_key: str, **fields: Any) -> None:
        """Emit a structured warning when a caller configured a diagnostic sink."""
        if self._diagnostic_sink is None:
            return
        self._diagnostic_sink(ProviderDiagnostic(message_key=message_key, fields=fields))

    def scan(self) -> list[Session]:
        """Scan all available sessions without a time limit."""
        return self.get_sessions(days=None)

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this agent tool is installed and has sessions.
        """
        pass

    @abstractmethod
    def get_sessions(self, days: int | None = 7) -> list[Session]:
        """
        Get sessions from the last N days, or all sessions when days is None.
        """
        pass

    def _get_available_sessions(self, days: int | None = 7) -> tuple[bool, list[Session]]:
        """Read availability and the requested session window for scanner workflows."""
        if not self.is_available():
            return False, []
        return True, self.get_sessions(days)

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON. Returns the exported file path."""
        return self.export_session_with_fields(session, output_dir)

    def export_session_with_fields(
        self,
        session: Session,
        output_dir: Path,
        fields: Mapping[str, Any] | None = None,
    ) -> Path:
        """Export unified JSON after merging workflow-owned top-level fields."""
        payload = self._json_export_payload(session)
        output_path = self._build_output_path(session, output_dir, ".json")
        return write_session_json(output_path, payload, fields)

    def _json_export_payload(self, session: Session) -> dict[str, Any]:
        """Data to serialize for JSON export.

        走请求级缓存，同一条命令里 print/markdown/search 已经解析过的会话不再重解析。
        需要做导出专属变换的 provider 可直接修改返回值；缓存为每个消费者
        提供隔离的副本。
        """
        return self.get_cached_session_data(session)

    def get_formatted_title(self, session: Session) -> str:
        """Get formatted title for display"""
        return format_session_title(session)

    def get_session_uri(self, session: Session) -> str:
        """Get the agent session URI for a session"""
        return f"{self.name}://{session.id}"

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Find one session by id.

        Default implementation scans all sessions; providers should override
        with a direct lookup when their storage supports it.
        """
        for session in self.scan():
            if session.id == session_id:
                return session
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
        return build_session_head(
            session,
            self.get_session_facts(session),
            uri=self.get_session_uri(session),
            agent_display_name=self.display_name,
        )

    def get_session_summary_fields(self, session: Session) -> dict[str, str | int | None]:
        """Return reduced metadata fields for list/selector display."""
        return build_session_summary_fields(session, self.get_session_facts(session))

    def _build_output_path(self, session: Session, output_dir: Path, suffix: str) -> Path:
        """Build a safe output path for a session export."""
        return build_session_output_path(output_dir, session.id, suffix)

    def _build_raw_output_path(self, session: Session, output_dir: Path) -> Path:
        """Build output path for raw session export."""
        return self._build_output_path(session, output_dir, self.raw_export_suffix)

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        """Export the original session file when one exists."""
        output_path = self._build_raw_output_path(session, output_dir)
        return copy_raw_session_file(session, output_path, self.get_search_roots())

    @abstractmethod
    def get_session_data(self, session: Session) -> dict[str, Any]:
        """
        Get session data as a dictionary.
        Returns dict with keys: id, title, messages, etc.
        """
        pass

    def get_cached_session_data(self, session: Session) -> dict[str, Any]:
        """Get isolated session data from one cached read per change signal."""
        return self._session_data_cache.get(self, session)

    @contextmanager
    def lease_cached_session_data(self, session: Session) -> Iterator[dict[str, Any]]:
        """Yield isolated data while retaining the cached source only for this lease."""
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
