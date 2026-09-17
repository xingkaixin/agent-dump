"""Cherry Studio 2.x database discovery and active-branch reads."""

import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from agent_dump.paths import SearchRoot, resolve_env_path


def search_roots(db_path: Path | None) -> tuple[SearchRoot, ...]:
    if db_path is not None:
        return (SearchRoot("Cherry Studio database", db_path),)
    override = os.environ.get("CHERRY_STUDIO_USER_DATA_DIR")
    if override:
        return (SearchRoot("Cherry Studio userData", Path(override) / "Data" / "cherrystudio.sqlite"),)
    if sys.platform == "darwin":
        default = Path.home() / "Library" / "Application Support" / "CherryStudio"
    elif sys.platform == "win32":
        default = resolve_env_path("APPDATA", Path.home() / "AppData" / "Roaming") / "CherryStudio"
    else:
        default = resolve_env_path("XDG_CONFIG_HOME", Path.home() / ".config") / "CherryStudio"
    boot_path = Path.home() / ".cherrystudio" / "boot-config.json"
    roots = []
    if boot_path.is_file():
        config = json.loads(boot_path.read_text(encoding="utf-8"))
        for path in config.get("app.user_data_path", {}).values():
            if isinstance(path, str) and Path(path).is_absolute():
                roots.append(Path(path))
    roots.append(default)
    return tuple(
        SearchRoot("Cherry Studio userData", root / "Data" / "cherrystudio.sqlite") for root in dict.fromkeys(roots)
    )


def session_rows(
    conn: sqlite3.Connection, session_id: str | None = None, cutoff: int | None = None
) -> list[dict[str, Any]]:
    session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_session)")}
    # Cherry Studio added agent-session soft deletion in migration 0023.
    session_filter = "WHERE s.deleted_at IS NULL" if "deleted_at" in session_columns else ""
    rows = conn.execute(
        f"""
        SELECT * FROM (
            SELECT 'topic-' || id AS session_id, 'topic' AS kind, id, name, created_at, updated_at,
                   active_node_id, NULL AS directory
            FROM topic WHERE deleted_at IS NULL
            UNION ALL
            SELECT 'session-' || s.id, 'session', s.id, s.name, s.created_at, s.updated_at,
                   NULL, w.path
            FROM agent_session s LEFT JOIN agent_workspace w ON w.id = s.workspace_id
            {session_filter}
        ) WHERE (? IS NULL OR session_id = ?) AND (? IS NULL OR created_at >= ?)
        ORDER BY created_at DESC, session_id
        """,  # noqa: S608
        (session_id, session_id, cutoff, cutoff),
    )
    return [dict(row) for row in rows]


def message_rows(conn: sqlite3.Connection, session: dict[str, Any], *, full: bool) -> list[dict[str, Any]]:
    columns = "m.*" if full else "m.id, m.role, m.model_id, m.message_snapshot"
    if session["kind"] == "session":
        rows = conn.execute(
            f"SELECT {columns} FROM agent_session_message m WHERE session_id = ? ORDER BY created_at, id",  # noqa: S608
            (session["id"],),
        )
        return [dict(row) for row in rows]
    if not session["active_node_id"]:
        return []
    rows = conn.execute(
        f"""
        WITH RECURSIVE branch(id, parent_id) AS (
            SELECT id, parent_id FROM message WHERE id = ? AND topic_id = ? AND deleted_at IS NULL
            UNION
            SELECT m.id, m.parent_id FROM message m JOIN branch b ON m.id = b.parent_id
            WHERE m.topic_id = ? AND m.deleted_at IS NULL
        )
        SELECT {columns}, m.parent_id, json_array_length(m.data, '$.parts') AS parts_count
        FROM message m JOIN branch b ON m.id = b.id
        """,  # noqa: S608
        (session["active_node_id"], session["id"], session["id"]),
    )
    by_id = {row["id"]: dict(row) for row in rows}
    chain: list[dict[str, Any]] = []
    seen = set()
    node_id = session["active_node_id"]
    while node_id:
        if node_id in seen or node_id not in by_id:
            raise ValueError(f"Invalid Cherry Studio active branch: {session['id']}")
        seen.add(node_id)
        row = by_id[node_id]
        if row["role"] == "root":
            if row["parent_id"] is not None:
                raise ValueError(f"Invalid Cherry Studio root: {session['id']}")
            return list(reversed(chain))
        is_empty_leaf = node_id == session["active_node_id"] and row["role"] == "user" and not row["parts_count"]
        if not is_empty_leaf:
            chain.append(row)
        node_id = row["parent_id"]
    raise ValueError(f"Missing Cherry Studio root: {session['id']}")
