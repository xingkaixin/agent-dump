"""OpenCode agent handler."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Any

from agent_dump.agents.base import Session
from agent_dump.agents.message_types import NormalizedSessionData
from agent_dump.agents.opencode_messages import decode_message
from agent_dump.agents.sqlite_sessions import SQLiteSessionAgent
from agent_dump.coercion import safe_epoch_datetime, safe_float, safe_int
from agent_dump.diagnostics import DiagnosticError, source_missing
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot, resolve_data_home


class OpenCodeAgent(SQLiteSessionAgent):
    """Handler for OpenCode sessions."""

    provider_name = "opencode"
    provider_display_name = "OpenCode"

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        root = resolve_data_home(is_windows=False) / "opencode"
        explicit = os.environ.get("OPENCODE_DB")
        if explicit == ":memory:":
            return ()
        if explicit:
            return (SearchRoot("OPENCODE_DB", root / explicit),)
        roots = [SearchRoot("XDG/default opencode.db", root / "opencode.db")]
        legacy_root = resolve_data_home() / "opencode"
        if legacy_root != root:
            roots.append(SearchRoot("LOCALAPPDATA/APPDATA compatibility", legacy_root / "opencode.db"))
        roots.append(SearchRoot("local development fallback", Path("data/opencode/opencode.db")))
        return tuple(roots)

    def _select_sessions(self, conn: sqlite3.Connection, *, where_sql: str, params: tuple[Any, ...]) -> list[Session]:
        conn.execute("BEGIN")
        tables = _session_tables(conn)
        if "session_v2" not in tables:
            return super()._select_sessions(conn, where_sql=where_sql, params=params)

        count_sql = (
            "(SELECT COUNT(*) FROM session_message m WHERE m.session_id = s.id)"
            if "session_message" in tables
            else "NULL"
        )
        # Both SQL fragments come from the SQLite provider; external values remain bound parameters.
        rows = conn.execute(
            f"""SELECT s.id, s.title, s.time_created, s.time_updated, s.slug, s.directory,
                       s.version, s.summary_files, s.model, s.project_id, s.parent_id,
                       {count_sql} AS message_count
                FROM session_v2 s WHERE {where_sql}""",  # noqa: S608
            params,
        ).fetchall()
        sessions = [self._build_v2_session(row, self.db_path or Path("")) for row in rows]
        if "session" in tables:
            sessions.extend(
                super()._select_sessions(
                    conn,
                    where_sql=f"({where_sql}) AND NOT EXISTS (SELECT 1 FROM session_v2 v WHERE v.id = s.id)",  # noqa: S608
                    params=params,
                )
            )
        return sorted(sessions, key=lambda session: session.created_at, reverse=True)

    def _build_v2_session(self, row: sqlite3.Row, source_path: Path) -> Session:
        model = self._parse_json_dict(row["model"]) or {}
        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        return Session(
            id=row["id"],
            title=row["title"] or "Untitled",
            created_at=safe_epoch_datetime(row["time_created"], unit="ms") or epoch,
            updated_at=safe_epoch_datetime(row["time_updated"], unit="ms") or epoch,
            source_path=source_path,
            metadata={
                "opencode_schema": "v2",
                "slug": row["slug"],
                "directory": row["directory"],
                "version": row["version"],
                "summary_files": row["summary_files"],
                "message_count": row["message_count"],
                "project": row["project_id"],
                "model": model.get("id") if isinstance(model.get("id"), str) else None,
                "parent_id": row["parent_id"],
            },
        )

    def _build_session_data(self, conn: sqlite3.Connection, session: Session) -> NormalizedSessionData:
        conn.execute("BEGIN")
        tables = _session_tables(conn)
        if "session_v2" not in tables:
            if session.metadata.get("opencode_schema") == "v2":
                raise ValueError(f"OpenCode V2 session source is missing: {session.id}")
            return super()._build_session_data(conn, session)
        row = conn.execute("SELECT *, NULL AS message_count FROM session_v2 WHERE id = ?", (session.id,)).fetchone()
        if row is None:
            if session.metadata.get("opencode_schema") == "v2" or "session" not in tables:
                raise ValueError(f"OpenCode session is missing: {session.id}")
            return super()._build_session_data(conn, session)

        current = self._build_v2_session(row, session.source_path)
        messages = [
            decode_message(message)
            for message in conn.execute(
                "SELECT id, type, seq, time_created, data FROM session_message WHERE session_id = ? ORDER BY seq ASC",
                (session.id,),
            )
        ]
        metadata = dict(row)
        metadata.pop("message_count")
        for field in ("model", "metadata", "revert", "fork_boundary"):
            if field in metadata:
                metadata[field] = self._parse_json_dict(metadata[field])
        return {
            "id": current.id,
            "title": current.title,
            "slug": current.metadata.get("slug"),
            "directory": current.metadata.get("directory"),
            "version": current.metadata.get("version"),
            "time_created": safe_int(row["time_created"]),
            "time_updated": safe_int(row["time_updated"]),
            "summary_files": row["summary_files"],
            "metadata": metadata,
            "messages": messages,
            "stats": {
                "message_count": len(messages),
                "total_cost": safe_float(row["cost"]),
                "total_input_tokens": safe_int(row["tokens_input"]),
                "total_output_tokens": safe_int(row["tokens_output"]),
            },
        }

    def get_session_head(self, session: Session) -> dict[str, Any]:
        head = super().get_session_head(session)
        if session.metadata.get("opencode_schema") == "v2":
            head["subtargets"] = []
        return head

    def _missing_database_error(self, db_path: Path | None) -> DiagnosticError:
        return source_missing(
            "OpenCode database is missing",
            missing_path=db_path or "opencode.db",
            searched_roots=[root.render() for root in self.get_search_roots()],
            next_steps=(
                i18n.t(Keys.DIAG_STEP_OPENCODE_DB_EXISTS),
                i18n.t(Keys.DIAG_STEP_OPENCODE_DEV_DB),
            ),
        )


def _session_tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
