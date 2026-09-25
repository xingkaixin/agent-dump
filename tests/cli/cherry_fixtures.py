"""Synthetic Cherry Studio 2.0.14 tables, based on its snake_case Drizzle schema."""

import json
from pathlib import Path
import sqlite3


def create_cherry_db(path: Path, now_ms: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            CREATE TABLE topic (
                id TEXT PRIMARY KEY, name TEXT, active_node_id TEXT,
                created_at INTEGER, updated_at INTEGER, deleted_at INTEGER
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY, topic_id TEXT, parent_id TEXT, role TEXT,
                data TEXT NOT NULL, status TEXT, siblings_group_id INTEGER DEFAULT 0,
                model_id TEXT, message_snapshot TEXT, stats TEXT,
                created_at INTEGER, updated_at INTEGER, deleted_at INTEGER
            );
            CREATE INDEX message_topic_idx ON message(topic_id);
            CREATE TABLE agent_workspace (id TEXT PRIMARY KEY, name TEXT, path TEXT, type TEXT);
            CREATE TABLE agent_session (
                id TEXT PRIMARY KEY, name TEXT, workspace_id TEXT,
                created_at INTEGER, updated_at INTEGER, deleted_at INTEGER
            );
            CREATE TABLE agent_session_message (
                id TEXT PRIMARY KEY, session_id TEXT, role TEXT, data TEXT NOT NULL, status TEXT,
                model_id TEXT, message_snapshot TEXT, stats TEXT, created_at INTEGER, updated_at INTEGER
            );
            CREATE INDEX agent_message_session_idx ON agent_session_message(session_id, created_at, id);
        """)
        conn.execute(
            "INSERT INTO topic VALUES (?, ?, ?, ?, ?, NULL)", ("contract", "Cherry Chat", "empty", now_ms, now_ms)
        )
        snapshot = json.dumps({"id": "agent", "name": "Agent", "model": {"id": "gpt-4.1", "provider": "openai"}})
        for message_id, parent, role, content, timestamp in (
            ("root", None, "root", None, now_ms),
            ("user", "root", "user", "Cherry prompt", now_ms + 200),
            ("answer", "user", "assistant", "Cherry answer", now_ms),
            ("alternative", "user", "assistant", "Unselected reply", now_ms + 100),
            ("empty", "answer", "user", None, now_ms + 300),
        ):
            data = json.dumps({"parts": [{"type": "text", "text": content}] if content else []})
            conn.execute(
                "INSERT INTO message (id, topic_id, parent_id, role, data, status, model_id, message_snapshot, stats, created_at, updated_at) VALUES (?, 'contract', ?, ?, ?, 'success', ?, ?, '{}', ?, ?)",
                (
                    message_id,
                    parent,
                    role,
                    data,
                    "openai::gpt-4.1" if role == "assistant" else None,
                    snapshot if role == "assistant" else None,
                    timestamp,
                    timestamp,
                ),
            )
        conn.execute("UPDATE message SET siblings_group_id = 1 WHERE role = 'assistant'")
        conn.execute(
            "INSERT INTO agent_workspace VALUES ('workspace', 'Project', '/workspace/cherry-contract', 'user')"
        )
        conn.execute(
            "INSERT INTO agent_session VALUES ('contract', 'Cherry Agent', 'workspace', ?, ?, NULL)", (now_ms, now_ms)
        )
        for message_id, role, content in (
            ("a-user", "user", "Cherry prompt"),
            ("b-assistant", "assistant", "Cherry answer"),
        ):
            conn.execute(
                "INSERT INTO agent_session_message VALUES (?, 'contract', ?, ?, 'success', ?, ?, ?, ?, ?)",
                (
                    message_id,
                    role,
                    json.dumps({"parts": [{"type": "text", "text": content}]}),
                    "openai::gpt-4.1" if role == "assistant" else None,
                    snapshot if role == "assistant" else None,
                    json.dumps({"inputTokens": 12, "outputTokens": 7, "inputTokenDetails": {"cacheReadTokens": 3}})
                    if role == "assistant"
                    else None,
                    now_ms,
                    now_ms,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return path
