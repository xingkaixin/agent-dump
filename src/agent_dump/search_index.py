# ruff: noqa: S608
"""Local full-text search index using SQLite FTS5.

All SQL f-strings in this file use FTS5 virtual table names that are
hardcoded internal constants (_FTS_TABLES), never user input.
"""

from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import heapq
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, TypeVar

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.i18n import Keys
from agent_dump.private_files import ensure_private_dir, ensure_private_file
from agent_dump.query_semantics import (
    TextQuery,
    TextQueryMode,
    extract_transcript_searchable_text,
)
from agent_dump.session_data import (
    serialize_session_updated_signal,
    session_updated_signal,
)
from agent_dump.terminal_output import render_terminal_message
from agent_dump.time_utils import normalize_datetime_utc

_T = TypeVar("_T")


@dataclass(frozen=True)
class _IndexedRow:
    """An already-indexed session's freshness signature and stable FTS rowid."""

    signature: str
    fts_rowid: int


@dataclass(frozen=True)
class SearchResult:
    """A single search result."""

    agent_name: str
    session_id: str
    title: str
    snippet: str | None
    rank: float


_LiteralMatch = tuple[float, float, float, SearchResult]
_SessionKey = tuple[str, str]


_CJK_RANGE = ("\u4e00", "\u9fff")


def _has_cjk(text: str) -> bool:
    """Check if text contains CJK characters."""
    return any(_CJK_RANGE[0] <= char <= _CJK_RANGE[1] for char in text)


_ADJACENT_CJK_BOUNDARY = re.compile(f"(?<=[{_CJK_RANGE[0]}-{_CJK_RANGE[1]}])(?=[{_CJK_RANGE[0]}-{_CJK_RANGE[1]}])")


def _preprocess_for_unicode61(text: str) -> str:
    """Insert spaces between consecutive CJK characters.

    unicode61 tokenizer only splits on non-alphanumeric characters.
    Without spaces, a CJK string like '修复认证' is treated as a single
    token and substrings like '认证' cannot match. By inserting spaces
    between adjacent CJK characters, each character becomes its own token
    and can be matched independently.
    """
    # 零宽断言只在两个 CJK 字符之间插空格；逐字符 Python 循环会为会话正文构造一个
    # 等长的单字符 list，1 字符 str 约 50-60 字节，代价是正文体积的数十倍
    return _ADJACENT_CJK_BOUNDARY.sub(" ", text)


def _cleanup_unicode61_snippet(snippet: str) -> str:
    """Remove CJK tokenization spaces from highlighted snippets."""
    cleaned = " ".join(snippet.split())
    replacements = (
        (re.compile(r"\*\*([\u4e00-\u9fff]+)\*\*\s+\*\*([\u4e00-\u9fff]+)\*\*"), r"**\1\2**"),
        (re.compile(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])"), r"\1\2"),
        (re.compile(r"([\u4e00-\u9fff])\s+(\*\*[\u4e00-\u9fff])"), r"\1\2"),
        (re.compile(r"([\u4e00-\u9fff]\*\*)\s+([\u4e00-\u9fff])"), r"\1\2"),
    )
    changed = True
    while changed:
        changed = False
        for pattern, replacement in replacements:
            updated = pattern.sub(replacement, cleaned)
            if updated != cleaned:
                changed = True
                cleaned = updated
    return cleaned


def _get_default_index_path() -> Path:
    """Resolve platform-specific index path."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "agent-dump" / "search-index.db"
    return Path.home() / ".cache" / "agent-dump" / "search-index.db"


def _has_fts5(conn: sqlite3.Connection) -> bool:
    """Check the FTS5 features required by the index schema."""
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._agent_dump_fts5_probe USING fts5(dummy, tokenize='trigram')")
        conn.execute("DROP TABLE temp._agent_dump_fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def extract_session_searchable_text(agent: BaseAgent, session: Session) -> str | None:
    """Extract all searchable text from a session, or None when it could not be read.

    None 与 "" 的区别是刻意的：`""` 表示会话确实没有可搜索内容，可以正常记为
    已索引；`None` 表示这次读取失败了，调用方必须跳过 index_state 写入，否则
    一次瞬时失败会被永久缓存成「已索引且最新」，该会话在之后所有搜索里静默消失。
    """
    try:
        session_data = agent.get_cached_session_data(session)
    except Exception:
        return _fallback_extract_from_source(session.source_path)

    return _extract_searchable_text_from_data(session, session_data)


def extract_session_searchable_text_once(agent: BaseAgent, session: Session) -> str | None:
    """Extract searchable text while releasing the full parsed payload afterwards."""
    try:
        with agent.lease_cached_session_data(session) as session_data:
            return _extract_searchable_text_from_data(session, session_data)
    except Exception:
        return _fallback_extract_from_source(session.source_path)


def _extract_searchable_text_from_data(session: Session, session_data: Mapping[str, Any]) -> str | None:
    text = extract_transcript_searchable_text(session_data)
    if text is None:
        return _fallback_extract_from_source(session.source_path)
    return text


# 只有按会话切分的文本源才能整文件读取。SQLite provider 的 source_path 是整个
# 数据库（opencode.py:200、cursor.py:255），把它当文本读会把全库内容索引到单个
# session id 下，造成跨会话结果污染并让索引膨胀。
_PER_SESSION_TEXT_SUFFIXES = frozenset({".jsonl", ".json", ".txt", ".md", ".log"})


def _fallback_extract_from_source(source_path: Path) -> str | None:
    """Read text straight from a per-session source, or None when that is not possible."""
    try:
        if source_path.is_dir():
            parts = [
                jsonl_file.read_text(encoding="utf-8", errors="ignore")
                for jsonl_file in sorted(source_path.glob("*.jsonl"))
            ]
            return "\n".join(parts) if parts else None
        if source_path.is_file() and source_path.suffix.lower() in _PER_SESSION_TEXT_SUFFIXES:
            return source_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return None


def _build_fts_query(
    keyword: str | TextQuery,
    *,
    split_cjk: bool = False,
) -> str:
    """Build a syntactically valid FTS5 MATCH expression from user input.

    每个词都作为 FTS5 字符串字面量引用，词之间是 FTS5 默认的隐式 AND，因此任何输入
    都不可能构成语法错误。

    之前的实现在关键词含 AND/OR/NOT/NEAR/*/" 时原样透传，于是一个不配对的引号就会让
    MATCH 报语法错误，被上层的兜底吞掉，静默退化成子串扫描——匹配语义不同、还慢得多，
    而用户得不到任何解释。文档描述的一直是关键词搜索（README 的 --search 一节），
    操作符语法从未被承诺过，所以这里按文档收敛而不是新增开关。

    split_cjk 对应 unicode61 表：索引侧把相邻 CJK 字符拆成独立 token，查询侧也要拆开，
    但一个用户 term 仍保留在同一个 FTS phrase 中。这样 `认证` 只生成 `"认 证"`，不会
    退化成可在任意位置分别命中的 `"认" "证"`。
    """
    query = keyword if isinstance(keyword, TextQuery) else TextQuery.parse(keyword, TextQueryMode.SEARCH_TERMS)
    if query.is_empty:
        return ""
    literals = tuple(_preprocess_for_unicode61(literal) for literal in query.literals) if split_cjk else query.literals
    return " ".join('"{}"'.format(literal.replace('"', '""')) for literal in literals)


def _is_cjk_literal(literal: str) -> bool:
    return bool(literal) and all(_CJK_RANGE[0] <= char <= _CJK_RANGE[1] for char in literal)


def _select_query_fts_table(query: TextQuery) -> str | None:
    if query.is_empty:
        return None
    if query.mode is TextQueryMode.KEYWORD and any(char.isspace() for char in query.literals[0]):
        return None
    if all(_is_cjk_literal(literal) for literal in query.literals):
        return "sessions_fts"
    if not any(_has_cjk(literal) for literal in query.literals) and all(
        len(literal) >= 3 for literal in query.literals
    ):
        return "sessions_fts_trigram"
    return None


_FTS_TABLES = ("sessions_fts", "sessions_fts_trigram")

# 待索引会话数达到该阈值时向 stderr 提示进度（关键词过滤会隐式建索引，首次运行可能较慢）
_INDEX_PROGRESS_THRESHOLD = 10
_MAX_INDEX_PARSE_WORKERS = 32
# 每批同时驻留内存的会话正文数量上限，与解析并行度对齐
_INDEX_BATCH_SIZE = 32


def _epoch_seconds(value: datetime) -> float:
    """Session 时间统一成 epoch 秒，供 SQL 侧排序使用。"""
    return normalize_datetime_utc(value).timestamp()


def _batched(items: list[_T], size: int) -> Iterator[list[_T]]:
    """Yield fixed-size slices; itertools.batched needs Python 3.12."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _delete_fts_rows(conn: sqlite3.Connection, rowids: list[int]) -> None:
    """Delete both FTS tables' rows for the given index_state rowids.

    agent_name/session_id 在两张 FTS5 表里都是 UNINDEXED，按它们定位只能全表扫
    内容行，每行都是一整段会话正文；更新 K 个会话就是 O(K·N)。rowid 是 FTS5 的
    主键，删除按 B-tree 定位，整体降到 O(K log N)。
    """
    if not rowids:
        return
    params = [(rowid,) for rowid in rowids]
    for fts_table in _FTS_TABLES:
        conn.executemany(f"DELETE FROM {fts_table} WHERE rowid = ?", params)


class SearchIndex:
    """Local full-text search index backed by SQLite FTS5."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _get_default_index_path()
        ensure_private_dir(self._db_path.parent)
        self._available: bool | None = None

    @property
    def is_available(self) -> bool:
        """Check if FTS5 is available."""
        if self._available is None:
            conn = sqlite3.connect(self._db_path)
            ensure_private_file(self._db_path)
            try:
                self._available = _has_fts5(conn)
            finally:
                conn.close()
        return self._available

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self._db_path)
        # sqlite3 按 umask 建库文件；索引里是全部会话正文，必须收紧到仅所有者可读
        ensure_private_file(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _check_schema_ok(self, conn: sqlite3.Connection) -> bool:
        """Check if existing schema keys sessions by a stable FTS rowid."""
        try:
            cursor = conn.execute("PRAGMA table_info(index_state)")
            rows = cursor.fetchall()
        except Exception:
            return False
        columns = {row["name"] for row in rows}
        pk_columns = {row["name"] for row in rows if row["pk"]}
        return {"updated_signature", "session_updated_at"} <= columns and pk_columns == {"fts_rowid"}

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
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='index_state'")
            has_index_state = cursor.fetchone() is not None
            if has_index_state and not self._check_schema_ok(conn):
                self._drop_all_tables(conn)

            # AUTOINCREMENT 保证 rowid 永不复用：默认分配是 max(rowid)+1，删掉末尾行后
            # 会重发同一个值，一旦某张 FTS 表残留旧行就会被新会话的正文静默污染
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_state (
                    fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    updated_signature TEXT NOT NULL,
                    indexed_at REAL NOT NULL,
                    session_updated_at REAL NOT NULL,
                    session_created_at REAL NOT NULL,
                    UNIQUE (agent, session_id)
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
        """Incrementally add or refresh the provided sessions.

        Absence from this list is not deletion evidence because callers may pass a
        time or project window. Explicit clear/rebuild operations own deletion.
        Returns (added_count, removed_count), with removed_count kept at zero for
        compatibility.
        """
        if not self.is_available:
            return (0, 0)

        self.ensure_initialized()
        conn = self._get_connection()
        added = 0
        skipped: list[str] = []

        try:
            # Get currently indexed sessions for this agent
            cursor = conn.execute(
                "SELECT session_id, updated_signature, fts_rowid FROM index_state WHERE agent = ?",
                (agent.name,),
            )
            indexed = {row["session_id"]: _IndexedRow(row["updated_signature"], row["fts_rowid"]) for row in cursor}

            # Determine which sessions need updating
            to_update: list[tuple[Session, str]] = []
            for session in sessions:
                signature = serialize_session_updated_signal(session_updated_signal(agent, session))
                previous = indexed.get(session.id)
                if previous is None or previous.signature != signature:
                    to_update.append((session, signature))

            if len(to_update) >= _INDEX_PROGRESS_THRESHOLD:
                print(
                    render_terminal_message(
                        Keys.INDEX_UPDATE_PROGRESS,
                        agent=agent.display_name,
                        count=len(to_update),
                    ),
                    file=sys.stderr,
                )

            def _extract_text(item: tuple[Session, str]) -> str | None:
                session, _ = item
                return extract_session_searchable_text_once(agent, session)

            # 分批解析并即时写入：一次性 list(executor.map(...)) 会让全部待索引会话
            # 的正文同时驻留内存，会话历史大的用户可能直接 OOM
            for batch in _batched(to_update, _INDEX_BATCH_SIZE):
                max_workers = min(_MAX_INDEX_PARSE_WORKERS, len(batch))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    texts = list(executor.map(_extract_text, batch))

                for (session, signature), text in zip(batch, texts, strict=True):
                    if text is None:
                        # 读失败：不写 index_state，让下一次运行重试，而不是把失败
                        # 缓存成「已索引」导致该会话永久搜不到
                        skipped.append(session.id)
                        continue
                    previous = indexed.get(session.id)
                    self._write_session_rows(
                        conn,
                        agent_name=agent.name,
                        session=session,
                        signature=signature,
                        text=text,
                        fts_rowid=previous.fts_rowid if previous else None,
                    )
                    added += 1

            if skipped:
                print(
                    render_terminal_message(
                        Keys.WARN_INDEX_SKIPPED_SESSIONS,
                        agent=agent.display_name,
                        count=len(skipped),
                        examples=", ".join(skipped[:3]),
                    ),
                    file=sys.stderr,
                )

            conn.commit()
        finally:
            conn.close()

        return (added, 0)

    def search(
        self,
        keyword: str | TextQuery,
        *,
        agent_names: set[str] | None = None,
        session_keys: set[_SessionKey] | None = None,
        limit: int | None = None,
    ) -> list[SearchResult]:
        """Search the index for sessions matching the keyword.

        limit 由调用方在确认没有后置过滤时传入。排序在 SQL 里完整表达，包括
        rank 之后的三级 tiebreak——只按 bm25 排序再 LIMIT 会让平局顺序随
        SQLite 的行序漂移，翻页和「同一次搜索两次结果一致」都靠这个稳定序。
        """
        if not self.is_available:
            return []
        if session_keys is not None and not session_keys:
            return []

        self.ensure_initialized()
        query = keyword if isinstance(keyword, TextQuery) else TextQuery.parse(keyword, TextQueryMode.SEARCH_TERMS)
        if query.is_empty:
            return []
        fts_table = _select_query_fts_table(query)
        if fts_table is None:
            return self._scan_literal_query(
                query,
                agent_names=agent_names,
                session_keys=session_keys,
                limit=limit,
            )
        return self._search_fts(
            query,
            fts_table=fts_table,
            agent_names=agent_names,
            session_keys=session_keys,
            limit=limit,
        )

    def _search_fts(
        self,
        query: TextQuery,
        *,
        fts_table: str,
        agent_names: set[str] | None,
        session_keys: set[_SessionKey] | None,
        limit: int | None,
    ) -> list[SearchResult]:
        fts_query = _build_fts_query(query, split_cjk=fts_table == "sessions_fts")
        raw_join = ""
        raw_title = "f.title"
        raw_content = "f.content"
        if fts_table == "sessions_fts":
            raw_join = "JOIN sessions_fts_trigram raw ON raw.rowid = f.rowid"
            raw_title = "raw.title"
            raw_content = "raw.content"

        conn = self._get_connection()
        results: list[SearchResult] = []

        try:
            filters = [f"{fts_table} MATCH ?"]
            params: list[Any] = [fts_query]
            if agent_names:
                filters.append(f"f.agent_name IN ({','.join('?' * len(agent_names))})")
                params.extend(sorted(agent_names))

            limit_clause = ""
            if limit is not None and fts_table == "sessions_fts_trigram" and session_keys is None:
                limit_clause = "LIMIT ?"
                params.append(limit)

            sql = f"""
                SELECT f.agent_name, f.session_id, {raw_title} AS raw_title, {raw_content} AS raw_content,
                       snippet({fts_table}, 3, '**', '**', '...', 10) as snippet,
                       bm25({fts_table}) as rank
                FROM {fts_table} f
                {raw_join}
                JOIN index_state s ON s.fts_rowid = f.rowid
                WHERE {" AND ".join(filters)}
                ORDER BY rank, s.session_updated_at DESC, s.session_created_at DESC,
                         f.agent_name, f.session_id
                {limit_clause}
                """

            cursor = conn.execute(sql, params)

            # bm25 returns lower values for better matches, so we negate for ranking
            for row in cursor:
                session_key = (str(row["agent_name"]), str(row["session_id"]))
                if session_keys is not None and session_key not in session_keys:
                    continue
                fields = (row["raw_title"] or "", row["raw_content"] or "")
                evidence = query.find_match(fields)
                if evidence is None:
                    continue
                snippet = row["snippet"]
                if snippet and fts_table == "sessions_fts":
                    snippet = _cleanup_unicode61_snippet(snippet)
                if not snippet or not query.has_evidence(snippet):
                    snippet = evidence.snippet

                results.append(
                    SearchResult(
                        agent_name=session_key[0],
                        session_id=session_key[1],
                        title=row["raw_title"] or "",
                        snippet=snippet,
                        rank=-(row["rank"] or 0.0),
                    )
                )
                if limit is not None and len(results) >= limit:
                    break
        finally:
            conn.close()

        return results

    def _scan_literal_query(
        self,
        query: TextQuery,
        *,
        agent_names: set[str] | None,
        session_keys: set[_SessionKey] | None,
        limit: int | None,
    ) -> list[SearchResult]:
        conn = self._get_connection()
        try:
            filters: list[str] = []
            params: list[Any] = []
            if agent_names:
                filters.append(f"f.agent_name IN ({','.join('?' * len(agent_names))})")
                params.extend(sorted(agent_names))
            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
            cursor = conn.execute(
                f"""
                SELECT f.agent_name, f.session_id, f.title, f.content,
                       s.session_updated_at, s.session_created_at
                FROM sessions_fts_trigram f
                JOIN index_state s ON s.fts_rowid = f.rowid
                {where_clause}
                """,
                params,
            )

            def iter_matches() -> Iterator[_LiteralMatch]:
                for row in cursor:
                    session_key = (str(row["agent_name"]), str(row["session_id"]))
                    if session_keys is not None and session_key not in session_keys:
                        continue
                    fields = (row["title"] or "", row["content"] or "")
                    evidence = query.find_match(fields)
                    if evidence is None:
                        continue
                    rank = 1.0 if 0 in evidence.fully_matching_field_indexes else 0.0
                    yield (
                        -rank,
                        -row["session_updated_at"],
                        -row["session_created_at"],
                        SearchResult(
                            agent_name=session_key[0],
                            session_id=session_key[1],
                            title=fields[0],
                            snippet=evidence.snippet,
                            rank=rank,
                        ),
                    )

            def sort_key(item: _LiteralMatch) -> tuple[float, float, float, str, str]:
                return (item[0], item[1], item[2], item[3].agent_name, item[3].session_id)

            matched = (
                sorted(iter_matches(), key=sort_key)
                if limit is None
                else heapq.nsmallest(limit, iter_matches(), key=sort_key)
            )
            return [item[3] for item in matched]
        finally:
            conn.close()

    def _write_session_rows(
        self,
        conn: sqlite3.Connection,
        *,
        agent_name: str,
        session: Session,
        signature: str,
        text: str,
        fts_rowid: int | None,
    ) -> None:
        """Replace one session's rows in both FTS tables and its index_state row.

        fts_rowid 为 None 表示该会话此前没有索引行；此时先写 index_state 取得分配的
        rowid，再用同一个 rowid 写两张 FTS 表，三张表因此始终一一对应。
        """
        if fts_rowid is None:
            cursor = conn.execute(
                """INSERT INTO index_state (agent, session_id, source_path, updated_signature, indexed_at,
                                            session_updated_at, session_created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent_name,
                    session.id,
                    str(session.source_path),
                    signature,
                    time.time(),
                    _epoch_seconds(session.updated_at),
                    _epoch_seconds(session.created_at),
                ),
            )
            fts_rowid = cursor.lastrowid
        else:
            _delete_fts_rows(conn, [fts_rowid])
            conn.execute(
                """UPDATE index_state
                   SET source_path = ?, updated_signature = ?, indexed_at = ?,
                       session_updated_at = ?, session_created_at = ?
                   WHERE fts_rowid = ?""",
                (
                    str(session.source_path),
                    signature,
                    time.time(),
                    _epoch_seconds(session.updated_at),
                    _epoch_seconds(session.created_at),
                    fts_rowid,
                ),
            )

        conn.execute(
            "INSERT INTO sessions_fts (rowid, agent_name, session_id, title, content) VALUES (?, ?, ?, ?, ?)",
            (
                fts_rowid,
                agent_name,
                session.id,
                _preprocess_for_unicode61(session.title),
                _preprocess_for_unicode61(text),
            ),
        )
        conn.execute(
            "INSERT INTO sessions_fts_trigram (rowid, agent_name, session_id, title, content) VALUES (?, ?, ?, ?, ?)",
            (fts_rowid, agent_name, session.id, session.title, text),
        )

    def clear_agent(self, agent_name: str) -> int:
        """Remove all index entries for an agent. Returns deleted count."""
        if not self.is_available:
            return 0

        # rebuild() 会先 clear 再 update，首次运行时表还不存在，必须先建表再 DELETE
        self.ensure_initialized()

        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("SELECT fts_rowid FROM index_state WHERE agent = ?", (agent_name,))
            rowids = [row["fts_rowid"] for row in cursor.fetchall()]
            conn.execute("DELETE FROM index_state WHERE agent = ?", (agent_name,))
            _delete_fts_rows(conn, rowids)
            conn.commit()
            return len(rowids)
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
            cursor = conn.execute("SELECT agent, COUNT(*) as count FROM index_state GROUP BY agent")
            return {row["agent"]: {"sessions": row["count"]} for row in cursor.fetchall()}
        finally:
            conn.close()
