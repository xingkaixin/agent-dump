"""Synthetic current DeepChat schema; never reads an installed application's data."""

import json
from pathlib import Path
import sqlite3


def create_deepchat_db(path: Path, now_ms: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            CREATE TABLE new_sessions (
                id TEXT PRIMARY KEY, agent_id TEXT, title TEXT, project_dir TEXT,
                is_draft INTEGER DEFAULT 0, session_kind TEXT DEFAULT 'regular', parent_session_id TEXT,
                created_at INTEGER, updated_at INTEGER
            );
            CREATE TABLE deepchat_sessions (id TEXT PRIMARY KEY, provider_id TEXT, model_id TEXT);
            CREATE TABLE deepchat_messages (
                id TEXT PRIMARY KEY, session_id TEXT, order_seq INTEGER, role TEXT, content TEXT,
                status TEXT, metadata TEXT, created_at INTEGER, updated_at INTEGER
            );
            CREATE INDEX idx_messages_session ON deepchat_messages(session_id, order_seq);
            CREATE TABLE deepchat_user_messages (message_id TEXT PRIMARY KEY, text TEXT);
            CREATE TABLE deepchat_assistant_blocks (
                message_id TEXT, block_index INTEGER, block_type TEXT, status TEXT, text_content TEXT,
                tool_call_id TEXT, tool_name TEXT, tool_params TEXT, tool_response TEXT,
                action_type TEXT, image_mime_type TEXT, extra_json TEXT, updated_at INTEGER,
                PRIMARY KEY (message_id, block_index)
            );
            CREATE TABLE deepchat_user_message_files (
                message_id TEXT, ordinal INTEGER, name TEXT, path TEXT, mime_type TEXT, size INTEGER,
                metadata_json TEXT, PRIMARY KEY (message_id, ordinal)
            );
            CREATE TABLE deepchat_user_message_links (
                message_id TEXT, ordinal INTEGER, url TEXT, PRIMARY KEY (message_id, ordinal)
            );
        """)
        conn.execute(
            "INSERT INTO new_sessions (id, agent_id, title, project_dir, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "deepchat-contract",
                "deepchat",
                "DeepChat Contract",
                "/workspace/deepchat-contract",
                now_ms,
                now_ms + 1000,
            ),
        )
        conn.execute("INSERT INTO deepchat_sessions VALUES (?, ?, ?)", ("deepchat-contract", "openai", "gpt-4.1"))
        conn.executemany(
            "INSERT INTO deepchat_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "user-1",
                    "deepchat-contract",
                    1,
                    "user",
                    json.dumps({"text": "Old prompt"}),
                    "sent",
                    "{}",
                    now_ms,
                    now_ms,
                ),
                (
                    "assistant-1",
                    "deepchat-contract",
                    2,
                    "assistant",
                    json.dumps([{"type": "content", "content": "Old answer"}]),
                    "sent",
                    json.dumps({"model": "gpt-4.1", "provider": "openai", "inputTokens": 10, "outputTokens": 5}),
                    now_ms + 1000,
                    now_ms + 1000,
                ),
            ],
        )
        conn.execute("INSERT INTO deepchat_user_messages VALUES (?, ?)", ("user-1", "DeepChat prompt"))
        conn.execute(
            "INSERT INTO deepchat_assistant_blocks (message_id, block_index, block_type, status, text_content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("assistant-1", 0, "content", "success", "DeepChat answer", now_ms + 1000),
        )
        conn.commit()
    finally:
        conn.close()
    return path
