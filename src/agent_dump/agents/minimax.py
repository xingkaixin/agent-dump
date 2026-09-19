"""Read MiniMax Code CLI display sessions without running its migrations."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.agents.minimax_messages import decode_message
from agent_dump.agents.title_fallback import basename_title, resolve_session_title
from agent_dump.coercion import safe_epoch_datetime
from agent_dump.diagnostics import source_missing, unsupported_capability
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot, first_existing_search_root

_REQUIRED_COLUMNS = {
    "local_runtime_sessions": {
        "session_id",
        "columnar_version",
        "runtime",
        "visibility",
        "session_kind",
        "archived",
        "title",
        "workspace_dir",
        "parent_session_id",
        "created_at_ms",
        "updated_at_ms",
        "extra_data_json",
    },
    "local_runtime_message_rows": {
        "id",
        "session_id",
        "msg_id",
        "role",
        "turn_id",
        "source",
        "created_at_ms",
        "data_json",
    },
    "local_runtime_messages": {"session_id", "display_messages_json"},
    "local_runtime_message_row_migrations": {"session_id"},
}


class MiniMaxAgent(BaseAgent):
    """Provider for current v2/sqlite/runtime-state.sqlite display records."""

    provider_name = "minimax"
    provider_display_name = "MiniMax Code"
    unsupported_uri_formats = frozenset({"raw"})

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self.db_path = db_path

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        if self.db_path is not None:
            return (SearchRoot("MiniMax Code database", self.db_path),)
        root = Path.home() / ".minimax"
        label = "MiniMax Code ~/.minimax"
        for name in ("MINIMAX_DATA_DIR", "MAVIS_DATA_DIR"):
            if value := os.environ.get(name, "").strip():
                root = Path(value).expanduser()
                label = name
                break
        return (SearchRoot(f"{label}/v2/sqlite/runtime-state.sqlite", root / "v2" / "sqlite" / "runtime-state.sqlite"),)

    def is_available(self) -> bool:
        return first_existing_search_root(*self.get_search_roots()) is not None

    def get_session_change_sources(self, session: Session) -> tuple[Path, ...]:
        return (session.source_path, Path(f"{session.source_path}-wal"))

    @contextmanager
    def _connect_db(self, db_path: Path) -> Iterator[sqlite3.Connection]:
        if not db_path.is_file():
            raise source_missing(
                i18n.t(Keys.DIAG_MINIMAX_SOURCE_MISSING),
                missing_path=db_path,
                searched_roots=[root.render() for root in self.get_search_roots()],
            )
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("BEGIN")
            for table, required in _REQUIRED_COLUMNS.items():
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if not required <= columns:
                    raise unsupported_capability(
                        i18n.t(Keys.DIAG_MINIMAX_SCHEMA),
                        capability_gap=i18n.t(Keys.DIAG_MINIMAX_CURRENT_DATABASE_ONLY),
                        details=(str(db_path), table),
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
            for row in self._session_rows(conn, cutoff=cutoff):
                try:
                    if session := self._session(db_path, row):
                        sessions.append(session)
                except (ValueError, TypeError) as exc:
                    complete = False
                    self._report_diagnostic(
                        Keys.WARN_MINIMAX_SESSION_READ_FAILED, session_id=row["session_id"], error=str(exc)
                    )
        return ProviderDiscovery(available=True, sessions=tuple(sessions), complete=complete)

    def find_session_by_id(self, session_id: str) -> Session | None:
        db_path = first_existing_search_root(*self.get_search_roots())
        if db_path is None:
            return None
        with self._connect_db(db_path) as conn:
            rows = self._session_rows(conn, session_id=session_id)
            return self._session(db_path, rows[0]) if rows else None

    def _session_rows(
        self, conn: sqlite3.Connection, *, session_id: str | None = None, cutoff: int | None = None
    ) -> list[sqlite3.Row]:
        conditions = []
        params: list[Any] = []
        if session_id is not None:
            conditions.append("s.session_id = ?")
            params.append(session_id)
        if cutoff is not None:
            conditions.append("COALESCE(s.created_at_ms, s.updated_at_ms) >= ?")
            params.append(cutoff)
        where = " AND ".join(conditions) or "1 = 1"
        return conn.execute(
            f"""
            SELECT s.session_id, s.columnar_version, s.runtime, s.visibility, s.session_kind, s.archived,
                   s.title, s.workspace_dir, s.parent_session_id, s.created_at_ms, s.updated_at_ms, s.extra_data_json,
                   (SELECT COUNT(*) FROM local_runtime_message_rows m WHERE m.session_id = s.session_id) AS message_count,
                   (NOT EXISTS (SELECT 1 FROM local_runtime_message_row_migrations r WHERE r.session_id = s.session_id)
                    AND EXISTS (SELECT 1 FROM local_runtime_messages l WHERE l.session_id = s.session_id
                                AND trim(l.display_messages_json) <> '[]')) AS legacy_pending
            FROM local_runtime_sessions s WHERE {where}
            ORDER BY COALESCE(s.created_at_ms, s.updated_at_ms) DESC, s.session_id
            """,  # noqa: S608
            params,
        ).fetchall()

    def _session(self, db_path: Path, row: sqlite3.Row) -> Session | None:
        if row["columnar_version"] != 3 or row["legacy_pending"]:
            raise ValueError(i18n.t(Keys.DIAG_MINIMAX_MIGRATION_REQUIRED))
        if (
            row["runtime"] != "pi-agent"
            or row["visibility"] == "hidden"
            or row["session_kind"] not in {"conversation", "task", "unknown"}
        ):
            return None
        extra = json.loads(row["extra_data_json"])
        if not isinstance(extra, dict):
            raise ValueError(f"Invalid MiniMax Code session metadata: {row['session_id']}")
        created = row["created_at_ms"] if row["created_at_ms"] is not None else row["updated_at_ms"]
        created_at = safe_epoch_datetime(created, unit="ms")
        updated_at = safe_epoch_datetime(row["updated_at_ms"], unit="ms")
        if created_at is None or updated_at is None:
            raise ValueError(f"Invalid MiniMax Code session timestamp: {row['session_id']}")
        return Session(
            id=row["session_id"],
            title=resolve_session_title(row["title"], basename_title(row["workspace_dir"]), row["session_id"]),
            created_at=created_at,
            updated_at=updated_at,
            source_path=db_path,
            metadata={
                "directory": row["workspace_dir"],
                "model": extra.get("effectiveModel"),
                "message_count": row["message_count"],
                "parent_session_id": row["parent_session_id"],
                "session_kind": row["session_kind"],
                "archived": bool(row["archived"]),
            },
        )

    def get_session_data(self, session: Session) -> dict[str, Any]:
        with self._connect_db(session.source_path) as conn:
            rows = self._session_rows(conn, session_id=session.id)
            current = self._session(session.source_path, rows[0]) if rows else None
            if current is None:
                raise source_missing(
                    i18n.t(Keys.DIAG_MINIMAX_SOURCE_MISSING),
                    missing_path=session.source_path,
                    details=(f"session id: {session.id}",),
                )
            messages = [
                decode_message(dict(row))
                for row in conn.execute(
                    "SELECT msg_id, role, turn_id, source, created_at_ms, data_json FROM local_runtime_message_rows WHERE session_id = ? ORDER BY id",
                    (session.id,),
                )
            ]
        return {
            "id": current.id,
            "title": current.title,
            "directory": current.metadata["directory"],
            "model": current.metadata["model"],
            "parent_session_id": current.metadata["parent_session_id"],
            "time_created": int(current.created_at.timestamp() * 1000),
            "time_updated": int(current.updated_at.timestamp() * 1000),
            "messages": messages,
            "stats": {"message_count": len(messages)},
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
