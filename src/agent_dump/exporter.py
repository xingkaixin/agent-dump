"""
Session export functionality
"""

import json
from pathlib import Path
import sqlite3
from typing import Any


def export_session(db_path: Path, session: dict[str, Any], output_dir: Path) -> Path:
    """Export a single session to JSON"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Build session data
    session_data = {
        "id": session["id"],
        "title": session["title"],
        "slug": session["slug"],
        "directory": session["directory"],
        "version": session["version"],
        "time_created": session["time_created"],
        "time_updated": session["time_updated"],
        "summary_files": session["summary_files"],
        "stats": {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "message_count": 0,
        },
        "messages": [],
    }

    # Get messages for this session
    cursor.execute(
        """
        SELECT * FROM message
        WHERE session_id = ?
        ORDER BY time_created ASC
        """,
        (session["id"],),
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

        # Update session stats
        session_data["stats"]["message_count"] += 1
        if message["cost"]:
            session_data["stats"]["total_cost"] += message["cost"]
        tokens = message["tokens"] or {}
        session_data["stats"]["total_input_tokens"] += tokens.get("input", 0)
        session_data["stats"]["total_output_tokens"] += tokens.get("output", 0)

        # Get parts for this message
        cursor.execute(
            """
            SELECT * FROM part
            WHERE message_id = ?
            ORDER BY time_created ASC
            """,
            (msg_row["id"],),
        )

        for part_row in cursor.fetchall():
            part_data = json.loads(part_row["data"])
            part = {
                "type": part_data.get("type"),
                "time_created": part_row["time_created"],
            }

            if part["type"] == "text" or part["type"] == "reasoning":
                part["text"] = part_data.get("text", "")
            elif part["type"] == "tool":
                part["tool"] = part_data.get("tool")
                part["callID"] = part_data.get("callID")
                part["title"] = part_data.get("title", "")
                part["state"] = part_data.get("state", {})
            elif part["type"] in ["step-start", "step-finish"]:
                part["reason"] = part_data.get("reason")
                part["tokens"] = part_data.get("tokens")
                part["cost"] = part_data.get("cost")

            message["parts"].append(part)

        session_data["messages"].append(message)

    conn.close()

    # Save to file
    output_path = output_dir / f"{session['id']}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    return output_path


def export_sessions(db_path: Path, sessions: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    """Export multiple sessions"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("📤 Exporting sessions...")
    exported = []
    for session in sessions:
        output_path = export_session(db_path, session, output_dir)
        exported.append(output_path)
        print(f"  ✓ {session['title'][:50]}... → {output_path.name}")

    return exported
