"""
OpenCode agent handler
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.paths import ProviderRoots, first_existing_path


class OpenCodeAgent(BaseAgent):
    """Handler for OpenCode sessions"""

    def __init__(self):
        super().__init__("opencode", "OpenCode")
        self.db_path: Path | None = None

    def _find_db_path(self) -> Path | None:
        """Find the OpenCode database path"""
        roots = ProviderRoots.from_env_or_home()
        return first_existing_path(roots.opencode_root / "opencode.db", Path("data/opencode/opencode.db"))

    def is_available(self) -> bool:
        """Check if OpenCode database exists"""
        self.db_path = self._find_db_path()
        return self.db_path is not None

    def scan(self) -> list[Session]:
        """Scan for all available sessions"""
        if not self.db_path:
            return []
        return self.get_sessions(days=3650)  # ~10 years

    def get_sessions(self, days: int = 7) -> list[Session]:
        """Get sessions from the last N days"""
        if not self.db_path:
            return []

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cutoff_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        cursor.execute(
            """
            SELECT 
                s.id,
                s.title,
                s.time_created,
                s.time_updated,
                s.slug,
                s.directory,
                s.version,
                s.summary_files
            FROM session s
            WHERE s.time_created >= ?
            ORDER BY s.time_created DESC
            """,
            (cutoff_time,),
        )

        sessions = []
        for row in cursor.fetchall():
            sessions.append(
                Session(
                    id=row["id"],
                    title=row["title"] or "Untitled",
                    created_at=datetime.fromtimestamp(row["time_created"] / 1000),
                    updated_at=datetime.fromtimestamp(row["time_updated"] / 1000),
                    source_path=self.db_path,
                    metadata={
                        "slug": row["slug"],
                        "directory": row["directory"],
                        "version": row["version"],
                        "summary_files": row["summary_files"],
                    },
                )
            )

        conn.close()
        return sessions

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary"""
        if not self.db_path:
            raise FileNotFoundError("Database not found")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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

        for msg_row in cursor.fetchall():
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

            cursor.execute(
                "SELECT * FROM part WHERE message_id = ? ORDER BY time_created ASC",
                (msg_row["id"],),
            )

            for part_row in cursor.fetchall():
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

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to JSON"""
        session_data = self.get_session_data(session)

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
