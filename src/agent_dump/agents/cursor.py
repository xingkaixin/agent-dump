"""
Cursor agent handler
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.agents.cursor_storage import (
    BUBBLE_RANGE_BATCH_SIZE,
    CursorStore,
    key_prefix_bounds,
)
from agent_dump.agents.cursor_transcript import CursorTranscriptDecoder, parse_cursor_iso_utc
from agent_dump.coercion import safe_epoch_datetime, safe_float
from agent_dump.diagnostics import unsupported_capability
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot

_EPOCH_UTC = datetime.fromtimestamp(0, tz=timezone.utc)
_BUBBLE_RANGE_BATCH_SIZE = BUBBLE_RANGE_BATCH_SIZE
_key_prefix_bounds = key_prefix_bounds


class CursorAgent(BaseAgent):
    """Handler for Cursor sessions stored in SQLite."""

    provider_name = "cursor"
    provider_display_name = "Cursor"

    # Cursor 会话没有独立原始文件，markdown 渲染也未适配其数据形态
    unsupported_uri_formats = frozenset({"raw", "markdown"})

    def __init__(self) -> None:
        super().__init__()
        self._store = CursorStore()
        self._transcript_decoder = CursorTranscriptDecoder(self._store, self._build_session_from_composer_metadata)

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        return self._store.search_roots()

    def get_session_change_sources(self, session: Session) -> tuple[Path, ...]:
        """Track bubble edits even when composer timestamps do not advance."""
        database = session.source_path
        return (database, database.with_name(f"{database.name}-wal"))

    def is_available(self) -> bool:
        return self._store.is_available()

    def _extract_title(self, composer: dict[str, Any], composer_id: str) -> str:
        name = composer.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        title = composer.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return f"Cursor Session {composer_id[:8]}"

    def _parse_datetime_utc(self, value: Any) -> datetime | None:
        if isinstance(value, str) and "T" in value:
            parsed = parse_cursor_iso_utc(value)
            if parsed is not None:
                return parsed
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            number = safe_float(value, default=float("nan"))
            # Cursor 同一字段既可能存秒也可能存毫秒，1e12 秒约合公元 33658 年，
            # 超过即判定为毫秒
            unit = "ms" if number > 1e12 else "s"
            return safe_epoch_datetime(number, unit=unit)
        return None

    def _resolve_session_times(self, composer: dict[str, Any]) -> tuple[datetime, datetime]:
        """Resolve created/updated times; unknown timestamps degrade to epoch instead of 'now'."""
        created = self._parse_datetime_utc(composer.get("createdAt"))
        updated_raw = composer.get("updatedAt") or composer.get("lastUpdatedAt") or composer.get("lastSendTime")
        updated = self._parse_datetime_utc(updated_raw)
        created_at = created or updated or _EPOCH_UTC
        return created_at, (updated or created_at)

    def _build_session_metadata(self, composer: dict[str, Any], *, composer_id: str, request_id: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "composer_id": composer_id,
            "request_id": request_id,
            "parent_composer_id": None,
            "subagent_composer_ids": [],
            "usage_data": composer.get("usageData"),
            "model": self._extract_composer_model(composer),
            "message_count": 0,
        }
        subagent_info = composer.get("subagentInfo")
        if isinstance(subagent_info, dict):
            parent_id = subagent_info.get("parentComposerId")
            if isinstance(parent_id, str) and parent_id:
                metadata["parent_composer_id"] = parent_id
        sub_ids = composer.get("subagentComposerIds")
        if isinstance(sub_ids, list):
            metadata["subagent_composer_ids"] = [str(x) for x in sub_ids if isinstance(x, str)]
        return metadata

    def _extract_composer_model(self, composer: dict[str, Any]) -> str | None:
        model_config = composer.get("modelConfig")
        if isinstance(model_config, dict):
            model_name = model_config.get("modelName")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()
        return None

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        """Get Cursor sessions from the requested time window."""
        return list(self.discover_sessions(days).sessions)

    def discover_sessions(self, days: int | None = 7) -> ProviderDiscovery:
        """Open the store once to establish availability and read sessions."""
        global_db_path = self._store.database_path()
        if not global_db_path.exists():
            return ProviderDiscovery(available=False)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days is not None else None
        sessions: list[Session] = []

        with self._store.reader() as reader:
            recent: list[tuple[str, dict[str, Any], datetime, datetime]] = []
            for record in reader.composers():
                created_at, updated_at = self._resolve_session_times(record.data)
                if cutoff is not None and created_at < cutoff:
                    continue
                recent.append((record.composer_id, record.data, created_at, updated_at))

            composer_ids = [item[0] for item in recent]
            bubble_summaries = reader.summarize_bubbles(composer_ids)

            for composer_id, composer, created_at, updated_at in recent:
                summary = bubble_summaries[composer_id]
                request_id = summary.request_id or composer_id
                metadata = self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id)
                metadata["message_count"] = summary.message_count
                metadata["model"] = metadata.get("model") or summary.model

                sessions.append(
                    Session(
                        id=request_id,
                        title=self._extract_title(composer, composer_id),
                        created_at=created_at,
                        updated_at=updated_at,
                        source_path=global_db_path,
                        metadata=metadata,
                    )
                )
        return ProviderDiscovery(available=True, sessions=tuple(sessions))

    def _build_session_from_composer(
        self,
        *,
        composer_id: str,
        request_id: str,
        composer: dict[str, Any],
    ) -> Session:
        session = self._build_session_from_composer_metadata(
            composer_id=composer_id,
            request_id=request_id,
            composer=composer,
        )
        with self._store.reader() as reader:
            summary = reader.summarize_bubbles([composer_id])[composer_id]
        session.metadata["message_count"] = summary.message_count
        session.metadata["model"] = session.metadata.get("model") or summary.model
        return session

    def _build_session_from_composer_metadata(
        self,
        *,
        composer_id: str,
        request_id: str,
        composer: dict[str, Any],
    ) -> Session:
        created_at, updated_at = self._resolve_session_times(composer)
        metadata = self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id)
        return Session(
            id=request_id,
            title=self._extract_title(composer, composer_id),
            created_at=created_at,
            updated_at=updated_at,
            source_path=self._store.database_path(),
            metadata=metadata,
        )

    def find_session_by_request_id(self, request_id: str) -> Session | None:
        """Resolve any bubble-level requestId to its owning composer session."""
        if not self._store.database_path().exists():
            return None
        with self._store.reader() as reader:
            composer_id = reader.find_composer_id_by_request_id(request_id)
            composer = reader.composer(composer_id) if composer_id is not None else None
        if composer_id is None or composer is None:
            return None
        return self._build_session_from_composer(
            composer_id=composer_id,
            request_id=request_id,
            composer=composer,
        )

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Resolve request ids via bubble lookup before falling back to a full scan."""
        matched = self.find_session_by_request_id(session_id)
        if matched is not None:
            return matched
        return super().find_session_by_id(session_id)

    def get_session_uri(self, session: Session) -> str:
        """Use request id as URI anchor for Cursor."""
        request_id = session.metadata.get("request_id") or session.id
        return f"cursor://{request_id}"

    def get_formatted_title(self, session: Session) -> str:
        """Render Cursor session title in local timezone for display."""
        title = session.title[:60] + "..." if len(session.title) > 60 else session.title
        session_time = session.created_at
        if session_time.tzinfo is not None:
            session_time = session_time.astimezone()
        time_str = session_time.strftime("%Y-%m-%d %H:%M")
        return f"{title} ({time_str})"

    def get_session_data(self, session: Session) -> dict[str, Any]:
        return self._transcript_decoder.build_session_data(session)

    def get_session_head(self, session: Session) -> dict[str, Any]:
        head = super().get_session_head(session)
        subtargets = session.metadata.get("subagent_composer_ids")
        if isinstance(subtargets, list):
            head["subtargets"] = [str(item) for item in subtargets if str(item).strip()]
        return head

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        raise unsupported_capability(
            "raw export is not supported for Cursor sessions",
            capability_gap="Cursor stores session state in SQLite, not as one raw session file",
            details=(f"session id: {session.id}",),
            next_steps=(
                i18n.t(Keys.DIAG_STEP_USE_JSON_OR_PRINT),
                i18n.t(Keys.DIAG_STEP_CURSOR_INSPECT_SQLITE),
            ),
        )
