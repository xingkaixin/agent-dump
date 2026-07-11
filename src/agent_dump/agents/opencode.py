"""
OpenCode agent handler
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import source_missing
from agent_dump.paths import ProviderRoots, SearchRoot, first_existing_search_root


class OpenCodeAgent(BaseAgent):
    """Handler for OpenCode sessions"""

    def __init__(self):
        super().__init__("opencode", "OpenCode")
        self.db_path: Path | None = None

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
        self.db_path = self._find_db_path()
        return self.db_path is not None

    def _connect_db(self) -> sqlite3.Connection:
        db_path = self.db_path
        if not db_path or not db_path.exists():
            raise source_missing(
                "OpenCode database is missing",
                missing_path=db_path or "opencode.db",
                searched_roots=[root.render() for root in self.get_search_roots()],
                next_steps=(
                    "确认 OpenCode 已在本机生成会话数据库。",
                    "若在测试或开发环境，检查 `data/opencode/opencode.db` 是否存在。",
                ),
            )

        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def scan(self) -> list[Session]:
        """Scan for all available sessions"""
        if not self.db_path:
            return []
        return self.get_sessions(days=3650)  # ~10 years

    def get_sessions(self, days: int = 7) -> list[Session]:
        """Get sessions from the last N days"""
        if not self.db_path:
            return []

        cutoff_time = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

        conn = self._connect_db()
        try:
            return self._select_sessions(conn, where_sql="s.time_created >= ?", params=(cutoff_time,))
        finally:
            conn.close()

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Look up one session directly by primary key."""
        if not self.db_path:
            return None

        conn = self._connect_db()
        try:
            sessions = self._select_sessions(conn, where_sql="s.id = ?", params=(session_id,))
        finally:
            conn.close()
        return sessions[0] if sessions else None

    def _select_sessions(
        self, conn: sqlite3.Connection, *, where_sql: str, params: tuple[Any, ...]
    ) -> list[Session]:
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
            created_at=datetime.fromtimestamp(row["time_created"] / 1000, tz=timezone.utc),
            updated_at=datetime.fromtimestamp(row["time_updated"] / 1000, tz=timezone.utc),
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

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary"""
        conn = self._connect_db()
        cursor = conn.cursor()

        session_data = {
            "id": session.id,
            "title": session.title,
            "slug": session.metadata.get("slug"),
            "directory": session.metadata.get("directory"),
            "version": session.metadata.get("version"),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": session.metadata.get("summary_files"),
            "stats": {
                "total_cost": 0,
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
            cursor.execute(
                """
                SELECT * FROM part
                WHERE message_id IN (SELECT value FROM json_each(?))
                ORDER BY message_id ASC, time_created ASC
                """,
                (json.dumps(chunk),),
            )
            for part_row in cursor.fetchall():
                message_id = str(part_row["message_id"])
                parts_by_message_id.setdefault(message_id, []).append(part_row)

        for msg_row in message_rows:
            msg_data = json.loads(msg_row["data"])

            message = {
                "id": msg_row["id"],
                "role": msg_data.get("role", "unknown"),
                "agent": msg_data.get("agent"),
                "mode": msg_data.get("mode"),
                "model": msg_data.get("modelID"),
                "provider": msg_data.get("providerID"),
                "time_created": msg_row["time_created"],
                "time_completed": msg_data.get("time", {}).get("completed"),
                "tokens": msg_data.get("tokens", {}),
                "cost": msg_data.get("cost", 0),
                "parts": [],
            }

            session_data["stats"]["message_count"] += 1
            if message["cost"]:
                session_data["stats"]["total_cost"] += message["cost"]
            tokens = message["tokens"] or {}
            session_data["stats"]["total_input_tokens"] += tokens.get("input", 0)
            session_data["stats"]["total_output_tokens"] += tokens.get("output", 0)

            for part_row in parts_by_message_id.get(str(msg_row["id"]), []):
                part_data = json.loads(part_row["data"])
                part = {
                    "type": part_data.get("type"),
                    "time_created": part_row["time_created"],
                }

                if part["type"] in ("text", "reasoning"):
                    part["text"] = part_data.get("text", "")
                elif part["type"] == "tool":
                    part["tool"] = part_data.get("tool")
                    part["callID"] = part_data.get("callID")
                    part["title"] = part_data.get("title", "")
                    part["state"] = part_data.get("state", {})
                elif part["type"] in ("step-start", "step-finish"):
                    part["reason"] = part_data.get("reason")
                    part["tokens"] = part_data.get("tokens")
                    part["cost"] = part_data.get("cost")

                message["parts"].append(part)

            session_data["messages"].append(message)

        conn.close()

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

        if not self.db_path:
            return head

        conn = self._connect_db()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) AS count FROM message WHERE session_id = ?", (session.id,))
            row = cursor.fetchone()
            head["message_count"] = int(row["count"]) if row else 0

            cursor.execute(
                "SELECT data FROM message WHERE session_id = ? ORDER BY time_created DESC",
                (session.id,),
            )
            for model_row in cursor.fetchall():
                try:
                    payload = json.loads(model_row["data"])
                except json.JSONDecodeError:
                    continue
                model = payload.get("modelID")
                if isinstance(model, str) and model.strip():
                    head["model"] = model.strip()
                    break
        finally:
            conn.close()

        return head

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to JSON"""
        session_data = self.get_session_data(session)

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return output_path

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        """Export raw session data for OpenCode.

        OpenCode stores sessions in SQLite, so raw export matches JSON export content
        while using a distinct filename.
        """
        session_data = self.get_session_data(session)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._build_raw_output_path(session, output_dir, suffix=".raw.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        return output_path
