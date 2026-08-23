"""
OpenCode agent handler
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, cast

from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.agents.message_assembly import (
    build_message,
    build_step_part,
    build_text_part,
    build_tool_part,
    normalize_message_role,
)
from agent_dump.agents.message_types import (
    NormalizedPart,
    NormalizedSessionData,
)
from agent_dump.coercion import safe_epoch_datetime, safe_float, safe_int
from agent_dump.diagnostics import DiagnosticError, source_missing
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import ProviderRoots, SearchRoot, first_existing_search_root
from agent_dump.private_files import write_private_text

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


class OpenCodeAgent(BaseAgent):
    """Handler for OpenCode sessions"""

    provider_name = "opencode"
    provider_display_name = "OpenCode"
    raw_export_suffix = ".raw.json"

    def __init__(self) -> None:
        super().__init__()
        self.db_path: Path | None = None
        self._db_path_discovered = False

    def _find_db_path(self) -> Path | None:
        """Find the OpenCode database path"""
        return first_existing_search_root(*self.get_search_roots())

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        roots = ProviderRoots.from_env_or_home()
        return (
            SearchRoot("XDG/LOCALAPPDATA opencode.db", roots.opencode_root / "opencode.db"),
            SearchRoot("local development fallback", Path("data/opencode/opencode.db")),
        )

    def is_available(self) -> bool:
        """Check if OpenCode database exists"""
        return self._ensure_db_path() is not None

    def _ensure_db_path(self) -> Path | None:
        if self.db_path is not None:
            self._db_path_discovered = True
            return self.db_path
        if not self._db_path_discovered:
            self.db_path = self._find_db_path()
            self._db_path_discovered = True
        return self.db_path

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

    def _connect_db(self) -> sqlite3.Connection:
        db_path = self.db_path
        if not db_path or not db_path.exists():
            raise self._missing_database_error(db_path)

        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        """Get sessions from the requested time window."""
        return list(self.discover_sessions(days).sessions)

    def discover_sessions(self, days: int | None = 7) -> ProviderDiscovery:
        """Read database availability and sessions through one discovered path."""
        if not self._ensure_db_path():
            return ProviderDiscovery(available=False)

        conn = self._connect_db()
        try:
            if days is None:
                sessions = self._select_sessions(conn, where_sql="1 = 1", params=())
            else:
                cutoff_time = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
                sessions = self._select_sessions(conn, where_sql="s.time_created >= ?", params=(cutoff_time,))
            return ProviderDiscovery(available=True, sessions=tuple(sessions))
        finally:
            conn.close()

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Look up one session directly by primary key."""
        if not self._ensure_db_path():
            return None

        conn = self._connect_db()
        try:
            sessions = self._select_sessions(conn, where_sql="s.id = ?", params=(session_id,))
        finally:
            conn.close()
        return sessions[0] if sessions else None

    def _select_sessions(self, conn: sqlite3.Connection, *, where_sql: str, params: tuple[Any, ...]) -> list[Session]:
        """Query sessions with an internal WHERE clause and build Session models."""
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'message'")
        has_message_table = cursor.fetchone() is not None

        if has_message_table:
            metadata_columns = """
                    (
                        SELECT COUNT(*)
                        FROM message m
                        WHERE m.session_id = s.id
                    ) AS message_count,
                    (
                        SELECT m.data
                        FROM message m
                        WHERE m.session_id = s.id AND m.data LIKE '%"modelID"%'
                        ORDER BY m.time_created DESC
                        LIMIT 1
                    ) AS model_message_data"""
        else:
            metadata_columns = """
                    0 AS message_count,
                    NULL AS model_message_data"""

        # where_sql 与 metadata_columns 都是本文件内的固定常量，参数全部占位符化
        cursor.execute(
            f"""
                SELECT
                    s.id,
                    s.title,
                    s.time_created,
                    s.time_updated,
                    s.slug,
                    s.directory,
                    s.version,
                    s.summary_files,{metadata_columns}
                FROM session s
                WHERE {where_sql}
                ORDER BY s.time_created DESC
                """,  # noqa: S608
            params,
        )
        return [self._build_session_from_row(row) for row in cursor.fetchall()]

    def _build_session_from_row(self, row: sqlite3.Row) -> Session:
        model: str | None = None
        raw_model_message = row["model_message_data"]
        if isinstance(raw_model_message, str) and raw_model_message.strip():
            try:
                model_data = json.loads(raw_model_message)
            except json.JSONDecodeError:
                model_data = {}
            model_id = model_data.get("modelID") if isinstance(model_data, dict) else None
            if isinstance(model_id, str) and model_id.strip():
                model = model_id.strip()

        return Session(
            id=row["id"],
            title=row["title"] or "Untitled",
            created_at=safe_epoch_datetime(row["time_created"], unit="ms") or _EPOCH,
            updated_at=safe_epoch_datetime(row["time_updated"], unit="ms") or _EPOCH,
            source_path=self.db_path if self.db_path else Path(""),
            metadata={
                "slug": row["slug"],
                "directory": row["directory"],
                "version": row["version"],
                "summary_files": row["summary_files"],
                "model": model,
                "message_count": row["message_count"],
            },
        )

    def _parse_json_dict(self, raw: Any) -> dict[str, Any] | None:
        """Parse a JSON object column; return None for NULL, invalid JSON, or non-object payloads."""
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def get_session_data(self, session: Session) -> dict[str, Any]:
        """Get session data as a dictionary"""
        conn = self._connect_db()
        try:
            return dict(self._build_session_data(conn, session))
        finally:
            conn.close()

    def _build_session_data(self, conn: sqlite3.Connection, session: Session) -> NormalizedSessionData:
        cursor = conn.cursor()

        session_data: NormalizedSessionData = {
            "id": session.id,
            "title": session.title,
            "slug": session.metadata.get("slug"),
            "directory": session.metadata.get("directory"),
            "version": session.metadata.get("version"),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": session.metadata.get("summary_files"),
            "stats": {
                "total_cost": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "message_count": 0,
            },
            "messages": [],
        }

        cursor.execute(
            "SELECT * FROM message WHERE session_id = ? ORDER BY time_created ASC",
            (session.id,),
        )
        message_rows = cursor.fetchall()
        parts_by_message_id: dict[str, list[sqlite3.Row]] = {str(row["id"]): [] for row in message_rows}
        message_ids = list(parts_by_message_id)

        for start in range(0, len(message_ids), 500):
            chunk = message_ids[start : start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            # SQL 文本只插入固定占位符；message id 仍由参数绑定，500 也低于旧 SQLite 的变量上限。
            part_query = f"""
                SELECT * FROM part
                WHERE message_id IN ({placeholders})
                ORDER BY message_id ASC, time_created ASC
                """  # noqa: S608
            cursor.execute(part_query, chunk)
            for part_row in cursor.fetchall():
                message_id = str(part_row["message_id"])
                parts_by_message_id.setdefault(message_id, []).append(part_row)

        for msg_row in message_rows:
            msg_data = self._parse_json_dict(msg_row["data"])
            if msg_data is None:
                self._report_diagnostic(Keys.WARN_MESSAGE_DATA_PARSE_FAILED, message_id=msg_row["id"])
                continue

            # time/tokens/cost 都由 OpenCode 写入：非 dict 的 time 会让 .get() 抛，
            # 字符串 cost 会让累加抛 TypeError，一条坏消息就中断整个 Session
            message_time = msg_data.get("time")
            tokens = msg_data.get("tokens")
            if not isinstance(tokens, dict):
                tokens = {}

            role = normalize_message_role(msg_data.get("role"))
            agent = msg_data.get("agent")
            mode = msg_data.get("mode")
            model = msg_data.get("modelID")
            provider = msg_data.get("providerID")
            cost = safe_float(msg_data.get("cost"))
            message = build_message(
                message_id=str(msg_row["id"]),
                role=role,
                agent=agent if isinstance(agent, str) else None,
                mode=mode if isinstance(mode, str) else None,
                model=model if isinstance(model, str) else None,
                provider=provider if isinstance(provider, str) else None,
                time_created=safe_int(msg_row["time_created"]),
                time_completed=message_time.get("completed") if isinstance(message_time, dict) else None,
                tokens=tokens,
                cost=cost,
                parts=[],
            )

            session_data["stats"]["message_count"] += 1
            session_data["stats"]["total_cost"] += cost
            session_data["stats"]["total_input_tokens"] += safe_int(tokens.get("input"))
            session_data["stats"]["total_output_tokens"] += safe_int(tokens.get("output"))

            for part_row in parts_by_message_id.get(str(msg_row["id"]), []):
                part_data = self._parse_json_dict(part_row["data"])
                if part_data is None:
                    self._report_diagnostic(Keys.WARN_PART_DATA_PARSE_FAILED, part_id=part_row["id"])
                    continue
                raw_part_type = part_data.get("type")
                part_type = raw_part_type if isinstance(raw_part_type, str) else "unknown"
                timestamp_ms = safe_int(part_row["time_created"])
                if part_type in ("text", "reasoning"):
                    text = part_data.get("text")
                    part = build_text_part(
                        text if isinstance(text, str) else "",
                        timestamp_ms,
                        part_type=part_type,
                    )
                elif part_type == "tool":
                    tool = part_data.get("tool")
                    call_id = part_data.get("callID")
                    title = part_data.get("title")
                    state = part_data.get("state")
                    part = build_tool_part(
                        tool_name=tool if isinstance(tool, str) else "",
                        call_id=call_id if isinstance(call_id, str) else "",
                        title=title if isinstance(title, str) else "",
                        state=state if isinstance(state, dict) else {},
                        timestamp_ms=timestamp_ms,
                    )
                elif part_type in ("step-start", "step-finish"):
                    part = build_step_part(
                        part_type=part_type,
                        timestamp_ms=timestamp_ms,
                        reason=part_data.get("reason"),
                        tokens=part_data.get("tokens"),
                        cost=part_data.get("cost"),
                    )
                else:
                    part = cast(NormalizedPart, {"type": part_type, "time_created": timestamp_ms})

                message["parts"].append(part)

            session_data["messages"].append(message)

        return session_data

    def _parse_summary_targets(self, raw_value: Any) -> list[str]:
        if raw_value is None:
            return []
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
            return [text]
        if isinstance(raw_value, list):
            return [str(item) for item in raw_value if str(item).strip()]
        return [str(raw_value)]

    def get_session_head(self, session: Session) -> dict[str, Any]:
        head = super().get_session_head(session)
        head["subtargets"] = self._parse_summary_targets(session.metadata.get("summary_files"))

        needs_message_count = "message_count" not in session.metadata
        needs_model = "model" not in session.metadata
        if not needs_message_count and not needs_model:
            return head

        if not self.db_path:
            return head

        conn = self._connect_db()
        cursor = conn.cursor()
        try:
            if needs_message_count:
                cursor.execute("SELECT COUNT(*) AS count FROM message WHERE session_id = ?", (session.id,))
                row = cursor.fetchone()
                head["message_count"] = safe_int(row["count"]) if row else 0

            if needs_model:
                cursor.execute(
                    "SELECT data FROM message WHERE session_id = ? ORDER BY time_created DESC",
                    (session.id,),
                )
                for model_row in cursor.fetchall():
                    payload = self._parse_json_dict(model_row["data"])
                    if payload is None:
                        continue
                    model = payload.get("modelID")
                    if isinstance(model, str) and model.strip():
                        head["model"] = model.strip()
                        break
        finally:
            conn.close()

        return head

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        """Export raw session data for OpenCode.

        OpenCode stores sessions in SQLite, so raw export matches JSON export content
        while using a distinct filename.
        """
        session_data = self.get_cached_session_data(session)
        output_path = self._build_raw_output_path(session, output_dir)
        return write_private_text(output_path, json.dumps(session_data, ensure_ascii=False, indent=2))
