"""Read current DeepChat transcripts without opening the application."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
from typing import Any

from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.agents.deepchat_messages import decode_message
from agent_dump.coercion import safe_epoch_datetime
from agent_dump.diagnostics import source_missing, unsupported_capability
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot, first_existing_search_root, resolve_env_path

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


class DeepChatAgent(BaseAgent):
    """Provider for unencrypted DeepChat app_db/agent.db databases."""

    provider_name = "deepchat"
    provider_display_name = "DeepChat"
    unsupported_uri_formats = frozenset({"raw"})

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self.db_path = db_path

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        if self.db_path is not None:
            return (SearchRoot("DeepChat database", self.db_path),)
        if sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support" / "DeepChat"
        elif sys.platform == "win32":
            root = resolve_env_path("APPDATA", Path.home() / "AppData" / "Roaming") / "DeepChat"
        else:
            root = resolve_env_path("XDG_CONFIG_HOME", Path.home() / ".config") / "DeepChat"
        root = resolve_env_path("DEEPCHAT_USER_DATA_DIR", root)
        return (SearchRoot("DeepChat userData/app_db/agent.db", root / "app_db" / "agent.db"),)

    def is_available(self) -> bool:
        return first_existing_search_root(*self.get_search_roots()) is not None

    def get_session_change_sources(self, session: Session) -> tuple[Path, ...]:
        return (session.source_path, Path(f"{session.source_path}-wal"))

    @contextmanager
    def _connect_db(self, db_path: Path) -> Iterator[sqlite3.Connection]:
        if not db_path.is_file():
            raise source_missing(
                i18n.t(Keys.DIAG_DEEPCHAT_SOURCE_MISSING),
                missing_path=db_path,
                searched_roots=[root.render() for root in self.get_search_roots()],
            )
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("BEGIN")
            yield conn
        except sqlite3.DatabaseError as exc:
            if "file is not a database" in str(exc).lower():
                raise unsupported_capability(
                    i18n.t(Keys.DIAG_DEEPCHAT_UNREADABLE),
                    capability_gap=i18n.t(Keys.DIAG_DEEPCHAT_PLAIN_DATABASE_ONLY),
                    details=(str(db_path),),
                ) from exc
            raise
        finally:
            conn.close()

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        return list(self.discover_sessions(days).sessions)

    def discover_sessions(self, days: int | None = 7) -> ProviderDiscovery:
        db_path = first_existing_search_root(*self.get_search_roots())
        if db_path is None:
            return ProviderDiscovery(available=False)
        cutoff = None if days is None else int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        with self._connect_db(db_path) as conn:
            sessions = self._select_sessions(conn, db_path, cutoff=cutoff)
        return ProviderDiscovery(available=True, sessions=tuple(sessions))

    def find_session_by_id(self, session_id: str) -> Session | None:
        db_path = first_existing_search_root(*self.get_search_roots())
        if db_path is None:
            return None
        with self._connect_db(db_path) as conn:
            sessions = self._select_sessions(conn, db_path, session_id=session_id)
        return sessions[0] if sessions else None

    def _select_sessions(
        self,
        conn: sqlite3.Connection,
        db_path: Path,
        *,
        session_id: str | None = None,
        cutoff: int | None = None,
    ) -> list[Session]:
        tables = _table_names(conn)
        if not {"new_sessions", "deepchat_sessions", "deepchat_messages"} <= tables:
            raise unsupported_capability(
                i18n.t(Keys.DIAG_DEEPCHAT_SCHEMA),
                capability_gap=i18n.t(Keys.DIAG_DEEPCHAT_CURRENT_DATABASE_ONLY),
                details=(str(db_path),),
            )
        conditions = ["s.is_draft = 0"]
        params: list[Any] = []
        if session_id is not None:
            conditions.append("s.id = ?")
            params.append(session_id)
        if cutoff is not None:
            conditions.append("s.created_at >= ?")
            params.append(cutoff)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT s.*, d.model_id, d.provider_id,
                   (SELECT COUNT(*) FROM deepchat_messages m WHERE m.session_id = s.id) AS message_count
            FROM new_sessions s
            LEFT JOIN deepchat_sessions d ON d.id = s.id
            WHERE {where}
            ORDER BY s.created_at DESC, s.id
            """,  # noqa: S608
            params,
        )
        return [
            Session(
                id=row["id"],
                title=row["title"] or "Untitled",
                created_at=safe_epoch_datetime(row["created_at"], unit="ms") or _EPOCH,
                updated_at=safe_epoch_datetime(row["updated_at"], unit="ms") or _EPOCH,
                source_path=db_path,
                metadata={
                    "directory": row["project_dir"],
                    "model": row["model_id"],
                    "provider": row["provider_id"],
                    "message_count": row["message_count"],
                    "agent": row["agent_id"],
                    "parent_session_id": row["parent_session_id"],
                    "session_kind": row["session_kind"],
                },
            )
            for row in rows
        ]

    def get_session_data(self, session: Session) -> dict[str, Any]:
        with self._connect_db(session.source_path) as conn:
            if not conn.execute("SELECT 1 FROM new_sessions WHERE id = ?", (session.id,)).fetchone():
                raise source_missing(
                    i18n.t(Keys.DIAG_DEEPCHAT_SOURCE_MISSING),
                    missing_path=session.source_path,
                    details=(f"session id: {session.id}",),
                )
            tables = _table_names(conn)
            users = _message_rows(conn, tables, "deepchat_user_messages", session.id, "message_id")
            blocks = _message_rows(conn, tables, "deepchat_assistant_blocks", session.id, "block_index")
            files = _message_rows(conn, tables, "deepchat_user_message_files", session.id, "ordinal")
            links = _message_rows(conn, tables, "deepchat_user_message_links", session.id, "ordinal")
            rows = conn.execute(
                "SELECT * FROM deepchat_messages WHERE session_id = ? ORDER BY order_seq, id", (session.id,)
            )
            messages = [
                decode_message(
                    dict(row),
                    user=users.get(row["id"], []),
                    blocks=blocks.get(row["id"], []),
                    files=files.get(row["id"], []),
                    links=links.get(row["id"], []),
                )
                for row in rows
            ]
        return {
            "id": session.id,
            "title": session.title,
            "directory": session.metadata.get("directory"),
            "model": session.metadata.get("model"),
            "parent_session_id": session.metadata.get("parent_session_id"),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "messages": messages,
            "stats": {
                "message_count": len(messages),
                "total_cost": 0.0,
                "total_input_tokens": sum(message["tokens"].get("input", 0) for message in messages),
                "total_output_tokens": sum(message["tokens"].get("output", 0) for message in messages),
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


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _message_rows(
    conn: sqlite3.Connection, tables: set[str], table: str, session_id: str, order_column: str
) -> dict[str, list[dict[str, Any]]]:
    if table not in tables:
        return {}
    columns = (
        "detail.message_id, detail.name, detail.path, detail.mime_type, detail.size"
        if table == "deepchat_user_message_files"
        else "detail.*"
    )
    # Table and ordering names are fixed by the calls above; only the session id is external.
    rows = conn.execute(
        f"""SELECT {columns} FROM {table} detail
            JOIN deepchat_messages m ON m.id = detail.message_id
            WHERE m.session_id = ? ORDER BY detail.message_id, detail.{order_column}""",  # noqa: S608
        (session_id,),
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["message_id"], []).append(dict(row))
    return grouped
