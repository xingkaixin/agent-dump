"""
Database operations for agent session export
"""

from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
from typing import Any


def find_db_path() -> Path:
    """Find the OpenCode database path"""
    paths = [
        os.path.expanduser("data/opencode/opencode.db"),
        os.path.expanduser("~/.local/share/opencode/opencode.db"),
    ]

    for path in paths:
        if os.path.exists(path):
            return Path(path)

    raise FileNotFoundError("Could not find opencode.db database")


def get_recent_sessions(db_path: Path, days: int = 7) -> list[dict[str, Any]]:
    """Get sessions from the last N days"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Calculate timestamp for N days ago (milliseconds)
    cutoff_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    # Query sessions with basic info
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
        # Convert timestamp to readable format
        created_dt = datetime.fromtimestamp(row["time_created"] / 1000)

        sessions.append(
            {
                "id": row["id"],
                "title": row["title"],
                "time_created": row["time_created"],
                "time_updated": row["time_updated"],
                "created_formatted": created_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "slug": row["slug"],
                "directory": row["directory"],
                "version": row["version"],
                "summary_files": row["summary_files"],
            }
        )

    conn.close()
    return sessions
