"""Synthetic OpenCode 2.0.15 projection rows, based on upstream session/sql.ts."""

import json
from pathlib import Path
import sqlite3
from typing import Any


def create_opencode_v2_db(path: Path, now: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE session_v2 (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, workspace_id TEXT,
                parent_id TEXT, fork_session_id TEXT, fork_boundary TEXT,
                slug TEXT NOT NULL, directory TEXT NOT NULL, path TEXT, title TEXT,
                version TEXT NOT NULL, summary_files INTEGER, metadata TEXT,
                cost REAL NOT NULL DEFAULT 0, tokens_input INTEGER NOT NULL DEFAULT 0,
                tokens_output INTEGER NOT NULL DEFAULT 0, tokens_reasoning INTEGER NOT NULL DEFAULT 0,
                tokens_cache_read INTEGER NOT NULL DEFAULT 0, tokens_cache_write INTEGER NOT NULL DEFAULT 0,
                revert TEXT, model TEXT, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
                time_archived INTEGER
            );
            CREATE TABLE session_message (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL,
                seq INTEGER NOT NULL, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
            );
            CREATE UNIQUE INDEX session_message_session_seq_idx ON session_message (session_id, seq);
        """)
        conn.execute(
            """INSERT INTO session_v2
                (id, project_id, slug, directory, title, version, summary_files, model,
                 cost, tokens_input, tokens_output, time_created, time_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "ses_v2",
                "proj_fixture",
                "fixture",
                "/workspace/opencode-v2",
                "OpenCode V2 Contract",
                "2.0.15",
                3,
                json.dumps({"id": "gpt-5", "providerID": "openai", "variant": "high"}),
                0.5,
                100,
                20,
                now,
                now + 1000,
            ),
        )
        insert_message(conn, "user", {"text": "OpenCode V2 prompt"}, seq=1, created=now)
        insert_message(
            conn,
            "assistant",
            {
                "agent": "build",
                "model": {"id": "gpt-5", "providerID": "openai", "variant": "high"},
                "content": [
                    {"type": "reasoning", "text": "Private reasoning"},
                    {"type": "text", "text": "OpenCode V2 answer"},
                    {
                        "type": "tool",
                        "id": "call_1",
                        "name": "bash",
                        "time": {"created": now, "completed": now + 1},
                        "state": {
                            "status": "completed",
                            "input": {"command": "echo ready"},
                            "content": [{"type": "text", "text": "工具结果 ready"}],
                        },
                    },
                ],
                "time": {"created": now + 1, "completed": now + 2},
                "cost": 0.25,
                "tokens": {"input": 40, "output": 10, "reasoning": 2, "cache": {"read": 8, "write": 0}},
            },
            seq=2,
            created=now + 1,
        )
    return path


def insert_message(
    conn: sqlite3.Connection,
    kind: str,
    data: dict[str, Any],
    *,
    seq: int,
    created: int = 1,
    session_id: str = "ses_v2",
) -> None:
    conn.execute(
        "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
        (f"msg_{seq}", session_id, kind, seq, created, created, json.dumps(data, ensure_ascii=False)),
    )
