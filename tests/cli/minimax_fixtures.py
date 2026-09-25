"""Synthetic MiniMax Code 0.4.12 display storage, isolated from installed clients."""

import json
from pathlib import Path
import sqlite3
from typing import Any


def create_minimax_db(path: Path, now_ms: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            CREATE TABLE local_runtime_sessions (
                session_id TEXT PRIMARY KEY, columnar_version INTEGER DEFAULT 3,
                runtime TEXT DEFAULT 'pi-agent', visibility TEXT DEFAULT 'visible',
                session_kind TEXT DEFAULT 'conversation', archived INTEGER DEFAULT 0,
                title TEXT, workspace_dir TEXT, parent_session_id TEXT,
                created_at_ms INTEGER, updated_at_ms INTEGER, extra_data_json TEXT DEFAULT '{}'
            );
            CREATE TABLE local_runtime_message_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                msg_id TEXT NOT NULL, role TEXT, turn_id TEXT, source TEXT,
                created_at_ms INTEGER NOT NULL, data_json TEXT NOT NULL,
                UNIQUE(session_id, msg_id)
            );
            CREATE TABLE local_runtime_messages (session_id TEXT PRIMARY KEY, display_messages_json TEXT NOT NULL);
            CREATE TABLE local_runtime_message_row_migrations (session_id TEXT PRIMARY KEY);
        """)
        conn.execute(
            """INSERT INTO local_runtime_sessions
               (session_id, title, workspace_dir, created_at_ms, updated_at_ms, extra_data_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "minimax-contract",
                "MiniMax Contract",
                "/workspace/minimax-contract",
                now_ms,
                now_ms + 1000,
                json.dumps({"effectiveModel": "minimax/MiniMax-M3"}),
            ),
        )
        conn.execute("INSERT INTO local_runtime_message_row_migrations VALUES (?)", ("minimax-contract",))
        insert_message(
            conn,
            {
                "msg_id": "user-1",
                "role": "user",
                "msg_content": "MiniMax prompt",
                "timestamp": now_ms,
                "attachments": [
                    {
                        "type": "file",
                        "file_path": "/not-read/spec.txt",
                        "file_name": "spec.txt",
                        "mime_type": "text/plain",
                    }
                ],
            },
        )
        insert_message(
            conn,
            {
                "msg_id": "assistant-1",
                "role": "assistant",
                "msg_type": 2,
                "msg_content": "MiniMax answer",
                "thinking_content": "private reasoning",
                "timestamp": now_ms + 1000,
                "usage": {"input_tokens": 30, "output_tokens": 10, "total_tokens": 45, "cache_read": 5},
                "tool_calls": [
                    {
                        "tool_name": "bash",
                        "tool_call_id": "tool-1",
                        "tool_call_status": 2,
                        "tool_call_args": json.dumps({"command": "printf ready"}),
                        "tool_call_result_data": json.dumps({"content": [{"type": "text", "text": "工具完成\nready"}]}),
                        "tool_call_duration_ms": 12,
                    }
                ],
            },
        )
        conn.commit()
    finally:
        conn.close()
    return path


def insert_message(conn: sqlite3.Connection, message: dict[str, Any], session_id: str = "minimax-contract") -> None:
    conn.execute(
        """INSERT INTO local_runtime_message_rows (session_id, msg_id, role, turn_id, source, created_at_ms, data_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            message["msg_id"],
            message.get("role"),
            "turn-1",
            "agent",
            message.get("timestamp", 0),
            json.dumps(message, ensure_ascii=True),
        ),
    )
