# ruff: noqa: S608
"""Local full-text search index using SQLite FTS5.

All SQL f-strings in this file use FTS5 virtual table names that are
hardcoded internal constants (_FTS_TABLES), never user input.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.message_filter import get_text_content_parts


@dataclass(frozen=True)
class SearchResult:
    """A single search result."""

    agent_name: str
    session_id: str
    title: str
    snippet: str | None
    rank: float


_CJK_RANGE = ("\u4e00", "\u9fff")


def _has_cjk(text: str) -> bool:
    """Check if text contains CJK characters."""
    return any(_CJK_RANGE[0] <= char <= _CJK_RANGE[1] for char in text)


def _preprocess_for_unicode61(text: str) -> str:
    """Insert spaces between consecutive CJK characters.

    unicode61 tokenizer only splits on non-alphanumeric characters.
    Without spaces, a CJK string like '修复认证' is treated as a single
    token and substrings like '认证' cannot match. By inserting spaces
    between adjacent CJK characters, each character becomes its own token
    and can be matched independently.
    """
    result: list[str] = []
    prev_was_cjk = False
    for char in text:
        is_cjk = _CJK_RANGE[0] <= char <= _CJK_RANGE[1]
        if prev_was_cjk and is_cjk:
            result.append(" ")
        result.append(char)
        prev_was_cjk = is_cjk
    return "".join(result)


def _get_default_index_path() -> Path:
    """Resolve platform-specific index path."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "agent-dump" / "search-index.db"
    return Path.home() / ".cache" / "agent-dump" / "search-index.db"


def _has_fts5(conn: sqlite3.Connection) -> bool:
    """Check if SQLite was compiled with FTS5 support."""
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(dummy)")
        conn.execute("DROP TABLE _fts5_test")
        return True
    except sqlite3.OperationalError:
        return False


def _extract_source_mtime(source_path: Path) -> float:
    """Get modification time for a source path (file or directory)."""
    if not source_path.exists():
        return 0.0
    if source_path.is_file():
        return source_path.stat().st_mtime
    if source_path.is_dir():
        max_mtime = source_path.stat().st_mtime
        for child in source_path.rglob("*"):
            if child.is_file():
                max_mtime = max(max_mtime, child.stat().st_mtime)
        return max_mtime
    return 0.0


def _serialize_for_search(value: Any) -> str:
    """Serialize a value to searchable text."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _extract_session_searchable_text(agent: BaseAgent, session: Session) -> str:
    """Extract all searchable text from a session."""
    try:
        session_data = agent.get_session_data(session)
    except Exception:
        return _fallback_extract_from_source(session.source_path)

    messages = session_data.get("messages")
    if not isinstance(messages, list):
        return _fallback_extract_from_source(session.source_path)

    text_parts: list[str] = []

    for message in messages:
        if not isinstance(message, dict):
            continue

        # Extract text from parts
        contents = get_text_content_parts(message)

        # Also extract content field (used by some agents)
        raw_content = message.get("content")
        if isinstance(raw_content, str) and raw_content.strip():
            contents.append(raw_content)
        elif isinstance(raw_content, list):
            for item in raw_content:
                if isinstance(item, str) and item.strip():
                    contents.append(item)
                elif isinstance(item, dict):
                    text = str(item.get("text", "")).strip()
                    if text:
                        contents.append(text)

        # Extract tool state
        parts = message.get("parts", [])
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool":
                    state = part.get("state", {})
                    if isinstance(state, dict):
                        arguments = state.get("arguments")
                        if arguments is not None:
                            contents.append(_serialize_for_search(arguments))
                        output = state.get("output")
                        if output is not None:
                            contents.append(_serialize_for_search(output))
                        prompt = state.get("prompt")
                        if prompt:
                            contents.append(str(prompt))

        for content in contents:
            if content and content.strip():
                text_parts.append(content.strip())

    return "\n\n".join(text_parts)


def _fallback_extract_from_source(source_path: Path) -> str:
    """Fallback: read text directly from source files."""
    try:
        if source_path.is_file():
            with open(source_path, encoding="utf-8", errors="ignore") as f:
                return f.read()
        if source_path.is_dir():
            parts = []
            for jsonl_file in sorted(source_path.glob("*.jsonl")):
                with open(jsonl_file, encoding="utf-8", errors="ignore") as f:
                    parts.append(f.read())
            return "\n".join(parts)
    except Exception:  # noqa: S110
        pass
    return ""


def _build_fts_query(keyword: str) -> str:
    """Build FTS5 MATCH query from user input."""
    keyword = keyword.strip()
    if not keyword:
        return ""

    # Pass through if user provided explicit FTS5 syntax
    if any(op in keyword for op in ("AND ", "OR ", "NOT ", "NEAR ", "*", '"')):
        return keyword

    # FTS5 default: spaces between terms are implicit AND
    return keyword


def _select_fts_table(keyword: str) -> str:
    """CJK queries always use unicode61 with preprocessing.

    Non-CJK queries use trigram for better substring matching.
    """
    if _has_cjk(keyword):
        return "sessions_fts"
    return "sessions_fts_trigram"


_FTS_TABLES = ("sessions_fts", "sessions_fts_trigram")


def _delete_fts_by_session(
    conn: sqlite3.Connection, fts_table: str, session_id: str, agent_name: str
) -> None:
    """Delete FTS rows for a specific session."""
    cursor = conn.execute(
        f"SELECT rowid FROM {fts_table} WHERE session_id = ? AND agent_name = ?",
        (session_id, agent_name),
    )
    for row in cursor.fetchall():
        conn.execute(
            f"DELETE FROM {fts_table} WHERE rowid = ?",
            (row["rowid"],),
        )


def _delete_fts_by_agent(
    conn: sqlite3.Connection, fts_table: str, agent_name: str
) -> None:
    """Delete FTS rows for a specific agent."""
    cursor = conn.execute(
        f"SELECT rowid FROM {fts_table} WHERE agent_name = ?",
        (agent_name,),
    )
    for row in cursor.fetchall():
        conn.execute(
            f"DELETE FROM {fts_table} WHERE rowid = ?",
            (row["rowid"],),
        )


class SearchIndex:
    """Local full-text search index backed by SQLite FTS5."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _get_default_index_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._available: bool | None = None

    @property
    def is_available(self) -> bool:
        """Check if FTS5 is available."""
        if self._available is None:
            conn = sqlite3.connect(self._db_path)
            try:
                self._available = _has_fts5(conn)
            finally:
                conn.close()
        return self._available

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _check_schema_ok(self, conn: sqlite3.Connection) -> bool:
        """Check if existing schema has all required columns."""
        try:
            cursor = conn.execute("PRAGMA table_info(index_state)")
            columns = {row["name"] for row in cursor.fetchall()}
            return "session_id" in columns
        except Exception:
            return False

    def _drop_all_tables(self, conn: sqlite3.Connection) -> None:
        """Drop all index tables for schema rebuild."""
        conn.execute("DROP TABLE IF EXISTS sessions_fts")
        conn.execute("DROP TABLE IF EXISTS sessions_fts_trigram")
        conn.execute("DROP TABLE IF EXISTS index_state")

    def ensure_initialized(self) -> None:
        """Create schema if not exists."""
        if not self.is_available:
            return

        conn = self._get_connection()
        try:
            # Schema migration: rebuild if old schema detected
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='index_state'"
            )
            has_index_state = cursor.fetchone() is not None
            if has_index_state and not self._check_schema_ok(conn):
                self._drop_all_tables(conn)

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_state (
                    source_path TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    indexed_at REAL NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                    agent_name UNINDEXED,
                    session_id UNINDEXED,
                    title,
                    content,
                    tokenize='unicode61 remove_diacritics 1'
                )
                """
            )

            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts_trigram USING fts5(
                    agent_name UNINDEXED,
                    session_id UNINDEXED,
                    title,
                    content,
                    tokenize='trigram'
                )
                """
            )

            conn.commit()
        finally:
            conn.close()

    def update(self, agent: BaseAgent, sessions: list[Session]) -> tuple[int, int]:
        """Incrementally update index for an agent's sessions.

        Returns (added_count, removed_count).
        """
        if not self.is_available:
            return (0, 0)

        self.ensure_initialized()
        conn = self._get_connection()
        added = 0
        removed = 0

        try:
            # Get currently indexed sessions for this agent
            cursor = conn.execute(
                "SELECT source_path, session_id, mtime FROM index_state WHERE agent = ?",
                (agent.name,),
            )
            indexed = {
                row["source_path"]: {"session_id": row["session_id"], "mtime": row["mtime"]}
                for row in cursor.fetchall()
            }

            # Determine which sessions need updating
            current_paths: set[str] = set()
            to_update: list[tuple[Session, float]] = []

            for session in sessions:
                path_str = str(session.source_path)
                current_paths.add(path_str)
                current_mtime = _extract_source_mtime(session.source_path)

                if path_str not in indexed or abs(indexed[path_str]["mtime"] - current_mtime) > 0.001:
                    to_update.append((session, current_mtime))

            # Remove stale entries
            stale_paths = [p for p in indexed if p not in current_paths]
            for path in stale_paths:
                session_id = indexed[path]["session_id"]
                conn.execute("DELETE FROM index_state WHERE source_path = ?", (path,))
                for fts_table in _FTS_TABLES:
                    _delete_fts_by_session(conn, fts_table, session_id, agent.name)
                removed += 1

            # Update changed/new entries
            for session, mtime in to_update:
                path_str = str(session.source_path)
                text = _extract_session_searchable_text(agent, session)

                # Delete old FTS entries for this session if updating
                for fts_table in _FTS_TABLES:
                    _delete_fts_by_session(conn, fts_table, session.id, agent.name)

                # Preprocess for unicode61 CJK support
                title_unicode = _preprocess_for_unicode61(session.title)
                text_unicode = _preprocess_for_unicode61(text)

                # Insert into FTS tables
                conn.execute(
                    "INSERT INTO sessions_fts (agent_name, session_id, title, content) VALUES (?, ?, ?, ?)",
                    (agent.name, session.id, title_unicode, text_unicode),
                )
                conn.execute(
                    "INSERT INTO sessions_fts_trigram (agent_name, session_id, title, content) VALUES (?, ?, ?, ?)",
                    (agent.name, session.id, session.title, text),
                )

                # Update index state
                conn.execute(
                    """INSERT INTO index_state (source_path, agent, session_id, mtime, indexed_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(source_path) DO UPDATE SET
                       agent=excluded.agent, session_id=excluded.session_id,
                       mtime=excluded.mtime, indexed_at=excluded.indexed_at""",
                    (path_str, agent.name, session.id, mtime, time.time()),
                )
                added += 1

            conn.commit()
        finally:
            conn.close()

        return (added, removed)

    def search(
        self,
        keyword: str,
        *,
        agent_names: set[str] | None = None,
    ) -> list[SearchResult]:
        """Search the index for sessions matching the keyword."""
        if not self.is_available:
            return []

        self.ensure_initialized()
        fts_query = _build_fts_query(keyword)
        if not fts_query:
            return []

        fts_table = _select_fts_table(keyword)

        # Preprocess CJK query for unicode61 matching
        if fts_table == "sessions_fts" and _has_cjk(keyword):
            fts_query = _preprocess_for_unicode61(fts_query)

        conn = self._get_connection()
        results: list[SearchResult] = []

        try:
            if agent_names:
                placeholders = ",".join("?" * len(agent_names))
                sql = (
                    f"""
                    SELECT agent_name, session_id, title,
                           snippet({fts_table}, 3, '**', '**', '...', 10) as snippet,
                           bm25({fts_table}) as rank
                    FROM {fts_table}
                    WHERE {fts_table} MATCH ? AND agent_name IN ({placeholders})
                    ORDER BY rank
                    """
                )
                params = (fts_query,) + tuple(agent_names)
            else:
                sql = (
                    f"""
                    SELECT agent_name, session_id, title,
                           snippet({fts_table}, 3, '**', '**', '...', 10) as snippet,
                           bm25({fts_table}) as rank
                    FROM {fts_table}
                    WHERE {fts_table} MATCH ?
                    ORDER BY rank
                    """
                )
                params = (fts_query,)

            cursor = conn.execute(sql, params)

            # bm25 returns lower values for better matches, so we negate for ranking
            for row in cursor.fetchall():
                snippet = row["snippet"]
                # Clean up spaces inserted by CJK preprocessing
                if snippet and fts_table == "sessions_fts":
                    snippet = " ".join(snippet.split())

                results.append(
                    SearchResult(
                        agent_name=row["agent_name"],
                        session_id=row["session_id"],
                        title=row["title"] or "",
                        snippet=snippet,
                        rank=-(row["rank"] or 0.0),
                    )
                )
        finally:
            conn.close()

        return results

    def clear_agent(self, agent_name: str) -> int:
        """Remove all index entries for an agent. Returns deleted count."""
        if not self.is_available:
            return 0

        conn = self._get_connection()
        try:
            for fts_table in _FTS_TABLES:
                _delete_fts_by_agent(conn, fts_table, agent_name)
            cursor = conn.execute(
                "DELETE FROM index_state WHERE agent = ? RETURNING source_path", (agent_name,)
            )
            deleted = len(cursor.fetchall())
            conn.commit()
            return deleted
        finally:
            conn.close()

    def rebuild(self, agent: BaseAgent, sessions: list[Session]) -> int:
        """Force rebuild index for an agent. Returns indexed count."""
        self.clear_agent(agent.name)
        added, _ = self.update(agent, sessions)
        return added

    def get_stats(self) -> dict[str, dict[str, int]]:
        """Get index statistics per agent."""
        if not self.is_available:
            return {}

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT agent, COUNT(*) as count FROM index_state GROUP BY agent"
            )
            return {row["agent"]: {"sessions": row["count"]} for row in cursor.fetchall()}
        finally:
            conn.close()
