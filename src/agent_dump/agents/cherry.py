"""Read Cherry Studio 2.x chats and agent sessions from SQLite."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any

from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.agents.cherry_messages import decode_message, message_model
from agent_dump.agents.cherry_storage import message_rows, search_roots, session_rows
from agent_dump.coercion import safe_epoch_datetime
from agent_dump.diagnostics import source_missing, unsupported_capability
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot, first_existing_search_root

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


class CherryStudioAgent(BaseAgent):
    """Provider for current Data/cherrystudio.sqlite databases."""

    provider_name = "cherry"
    provider_display_name = "Cherry Studio"
    unsupported_uri_formats = frozenset({"raw"})

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self.db_path = db_path

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        return search_roots(self.db_path)

    def is_available(self) -> bool:
        return first_existing_search_root(*self.get_search_roots()) is not None

    def get_session_change_sources(self, session: Session) -> tuple[Path, ...]:
        return (session.source_path, Path(f"{session.source_path}-wal"))

    @contextmanager
    def _connect_db(self, db_path: Path) -> Iterator[sqlite3.Connection]:
        if not db_path.is_file():
            raise source_missing(i18n.t(Keys.DIAG_CHERRY_SOURCE_MISSING), missing_path=db_path)
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("BEGIN")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not {"topic", "message", "agent_session", "agent_session_message", "agent_workspace"} <= tables:
                raise unsupported_capability(
                    i18n.t(Keys.DIAG_CHERRY_SCHEMA),
                    capability_gap=i18n.t(Keys.DIAG_CHERRY_CURRENT_DATABASE_ONLY),
                    details=(str(db_path),),
                )
            yield conn
        finally:
            conn.close()

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        return list(self.discover_sessions(days).sessions)

    def discover_sessions(self, days: int | None = 7) -> ProviderDiscovery:
        db_path = first_existing_search_root(*self.get_search_roots())
        if db_path is None:
            return ProviderDiscovery(available=False)
        cutoff = None if days is None else int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        sessions = []
        complete = True
        with self._connect_db(db_path) as conn:
            for row in session_rows(conn, cutoff=cutoff):
                try:
                    sessions.append(self._session(conn, db_path, row))
                except (ValueError, TypeError, AttributeError, sqlite3.DatabaseError) as exc:
                    complete = False
                    self._report_diagnostic(
                        Keys.WARN_CHERRY_SESSION_READ_FAILED, session_id=row["session_id"], error=str(exc)
                    )
        return ProviderDiscovery(available=True, sessions=tuple(sessions), complete=complete)

    def find_session_by_id(self, session_id: str) -> Session | None:
        db_path = first_existing_search_root(*self.get_search_roots())
        if db_path is None:
            return None
        with self._connect_db(db_path) as conn:
            rows = session_rows(conn, session_id=session_id)
            return self._session(conn, db_path, rows[0]) if rows else None

    def _session(self, conn: sqlite3.Connection, db_path: Path, row: dict[str, Any]) -> Session:
        messages = message_rows(conn, row, full=False)
        model = next(
            (
                model
                for message in reversed(messages)
                if message["role"] == "assistant" and (model := message_model(message)[0])
            ),
            None,
        )
        return Session(
            id=row["session_id"],
            title=row["name"] or "Untitled",
            created_at=safe_epoch_datetime(row["created_at"], unit="ms") or _EPOCH,
            updated_at=safe_epoch_datetime(row["updated_at"], unit="ms") or _EPOCH,
            source_path=db_path,
            metadata={"directory": row["directory"], "model": model, "message_count": len(messages)},
        )

    def get_session_data(self, session: Session) -> dict[str, Any]:
        with self._connect_db(session.source_path) as conn:
            rows = session_rows(conn, session_id=session.id)
            if not rows:
                raise source_missing(
                    i18n.t(Keys.DIAG_CHERRY_SOURCE_MISSING),
                    missing_path=session.source_path,
                    details=(f"session id: {session.id}",),
                )
            row = rows[0]
            messages = [decode_message(message) for message in message_rows(conn, row, full=True)]
        return {
            "id": session.id,
            "title": row["name"] or "Untitled",
            "directory": row["directory"],
            "time_created": row["created_at"],
            "time_updated": row["updated_at"],
            "messages": messages,
            "stats": {
                "message_count": len(messages),
                "total_cost": 0.0,
                "total_input_tokens": sum(message["tokens"]["input"] for message in messages),
                "total_output_tokens": sum(message["tokens"]["output"] for message in messages),
            },
        }

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        raise unsupported_capability(
            i18n.t(Keys.DIAG_URI_CAPABILITY_GAP, agent=self.display_name),
            capability_gap=i18n.t(
                Keys.DIAG_URI_CAPABILITY_DETAIL,
                agent=self.display_name,
                supported="json, markdown, print",
                requested="raw",
            ),
            next_steps=(i18n.t(Keys.DIAG_STEP_EXPORT_JSON_FIRST),),
        )
