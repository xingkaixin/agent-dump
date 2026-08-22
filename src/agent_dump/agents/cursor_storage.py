"""Read-only access to Cursor's SQLite-backed session store."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from agent_dump.coercion import safe_int
from agent_dump.diagnostics import DiagnosticError, source_missing
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot


def key_prefix_bounds(prefix: str) -> tuple[str, str]:
    """Return indexed bounds covering exactly one key prefix without a LIKE scan."""
    return prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)


def parse_cursor_json(raw: Any) -> dict[str, Any] | None:
    """Decode one Cursor JSON object, rejecting other shapes and bad input."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class CursorComposerRecord:
    composer_id: str
    data: dict[str, Any]


@dataclass(frozen=True)
class CursorBubbleRecord:
    bubble_id: str
    data: dict[str, Any] | None


@dataclass(frozen=True)
class CursorBubbleSummary:
    request_id: str | None
    message_count: int
    model: str | None


_BUBBLE_MESSAGE_COUNT_SQL = """
    SELECT substr(key, 10, instr(substr(key, 10), ':') - 1) AS composer_id,
           COUNT(*) AS message_count
    FROM cursorDiskKV
    WHERE ({key_ranges}) AND json_extract(value, '$.type') IN (1, 2)
    GROUP BY composer_id
"""

BUBBLE_RANGE_BATCH_SIZE = 100
_METADATA_BUBBLE_SCAN_LIMIT = 20


class CursorStoreReader:
    """A reusable read transaction over Cursor's key-value store."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def composers(self) -> list[CursorComposerRecord]:
        lower, upper = key_prefix_bounds("composerData:")
        rows = self._query(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY rowid DESC",
            (lower, upper),
        )
        records: list[CursorComposerRecord] = []
        for row in rows:
            data = parse_cursor_json(row["value"])
            if data is None:
                continue
            records.append(CursorComposerRecord(composer_id=str(row["key"]).split(":", 1)[1], data=data))
        return records

    def composer(self, composer_id: str) -> dict[str, Any] | None:
        rows = self._query(
            "SELECT value FROM cursorDiskKV WHERE key = ?",
            (f"composerData:{composer_id}",),
        )
        return parse_cursor_json(rows[0]["value"]) if rows else None

    def bubbles(self, composer_id: str) -> list[CursorBubbleRecord]:
        lower, upper = key_prefix_bounds(f"bubbleId:{composer_id}:")
        rows = self._query(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY key",
            (lower, upper),
        )

        return self._bubble_records(rows)

    def transcript_bubbles(self, composer_id: str) -> list[CursorBubbleRecord]:
        lower, upper = key_prefix_bounds(f"bubbleId:{composer_id}:")
        rows = self._query(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY rowid ASC",
            (lower, upper),
        )
        return self._bubble_records(rows)

    @staticmethod
    def _bubble_records(rows: list[sqlite3.Row]) -> list[CursorBubbleRecord]:
        return [
            CursorBubbleRecord(
                bubble_id=str(row["key"]).split(":")[-1],
                data=parse_cursor_json(row["value"]),
            )
            for row in rows
        ]

    def summarize_bubbles(self, composer_ids: list[str]) -> dict[str, CursorBubbleSummary]:
        counts = self._count_messages(composer_ids)
        if counts is None:
            return {composer_id: self._summarize(self.bubbles(composer_id)) for composer_id in composer_ids}

        metadata = self._scan_metadata(composer_ids)
        return {
            composer_id: CursorBubbleSummary(
                request_id=metadata.get(composer_id, (None, None))[0],
                message_count=counts.get(composer_id, 0),
                model=metadata.get(composer_id, (None, None))[1],
            )
            for composer_id in composer_ids
        }

    def find_composer_id_by_request_id(self, request_id: str) -> str | None:
        lower, upper = key_prefix_bounds("bubbleId:")
        rows = self._query(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key >= ? AND key < ? AND instr(value, ?) > 0 ORDER BY rowid DESC",
            (lower, upper, request_id),
        )
        for row in rows:
            bubble = parse_cursor_json(row["value"])
            if bubble is not None and bubble.get("requestId") == request_id:
                return str(row["key"]).split(":")[1]
        return None

    def _count_messages(self, composer_ids: list[str]) -> dict[str, int] | None:
        """Count only requested composers, falling back when SQLite lacks JSON1."""
        counts: dict[str, int] = {}
        for start in range(0, len(composer_ids), BUBBLE_RANGE_BATCH_SIZE):
            batch = composer_ids[start : start + BUBBLE_RANGE_BATCH_SIZE]
            params: list[str] = []
            for composer_id in batch:
                params.extend(key_prefix_bounds(f"bubbleId:{composer_id}:"))
            key_ranges = " OR ".join("(key >= ? AND key < ?)" for _ in batch)
            try:
                rows = self._query(_BUBBLE_MESSAGE_COUNT_SQL.format(key_ranges=key_ranges), tuple(params))
            except sqlite3.OperationalError:
                return None
            for row in rows:
                counts[str(row["composer_id"])] = safe_int(row["message_count"])
        return counts

    def _scan_metadata(self, composer_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
        """Read request ids and models from a bounded prefix of each composer."""
        summaries: dict[str, tuple[str | None, str | None]] = {}
        for start in range(0, len(composer_ids), BUBBLE_RANGE_BATCH_SIZE):
            batch = composer_ids[start : start + BUBBLE_RANGE_BATCH_SIZE]
            statements: list[str] = []
            params: list[str | int] = []
            for composer_id in batch:
                lower, upper = key_prefix_bounds(f"bubbleId:{composer_id}:")
                statements.append(
                    "SELECT * FROM ("
                    "SELECT ? AS composer_id, key, value FROM cursorDiskKV "
                    "WHERE key >= ? AND key < ? ORDER BY key LIMIT ?"
                    ")"
                )
                params.extend((composer_id, lower, upper, _METADATA_BUBBLE_SCAN_LIMIT))

            rows = self._query(" UNION ALL ".join(statements) + " ORDER BY composer_id, key", tuple(params))
            for row in rows:
                composer_id = str(row["composer_id"])
                request_id, model = summaries.get(composer_id, (None, None))
                bubble = parse_cursor_json(row["value"])
                if bubble is None:
                    continue
                if request_id is None:
                    raw_request_id = bubble.get("requestId")
                    if isinstance(raw_request_id, str) and raw_request_id.strip():
                        request_id = raw_request_id.strip()
                if model is None:
                    model_info = bubble.get("modelInfo")
                    model_name = model_info.get("modelName") if isinstance(model_info, dict) else None
                    if isinstance(model_name, str) and model_name.strip():
                        model = model_name.strip()
                summaries[composer_id] = (request_id, model)
        return summaries

    @staticmethod
    def _summarize(bubbles: list[CursorBubbleRecord]) -> CursorBubbleSummary:
        request_id: str | None = None
        message_count = 0
        model: str | None = None
        for record in bubbles:
            bubble = record.data
            if bubble is None:
                continue
            if bubble.get("type") in {1, 2}:
                message_count += 1
            if request_id is None:
                raw_request_id = bubble.get("requestId")
                if isinstance(raw_request_id, str) and raw_request_id.strip():
                    request_id = raw_request_id.strip()
            if model is None:
                model_info = bubble.get("modelInfo")
                model_name = model_info.get("modelName") if isinstance(model_info, dict) else None
                if isinstance(model_name, str) and model_name.strip():
                    model = model_name.strip()
        return CursorBubbleSummary(request_id=request_id, message_count=message_count, model=model)

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        return self._connection.execute(sql, params).fetchall()


class CursorStore:
    """Locate and read Cursor's global database without exposing SQLite upstream."""

    def database_path(self) -> Path:
        return self._default_user_root() / "globalStorage" / "state.vscdb"

    def search_roots(self) -> tuple[SearchRoot, ...]:
        return (SearchRoot("Cursor global state.vscdb", self.database_path()),)

    def is_available(self) -> bool:
        db_path = self.database_path()
        if not db_path.exists():
            return False
        try:
            sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True).close()
        except (sqlite3.Error, OSError):
            return False
        return True

    @contextmanager
    def reader(self) -> Iterator[CursorStoreReader]:
        db_path = self.database_path()
        if not db_path.exists():
            raise self._missing_database_error()
        connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield CursorStoreReader(connection)
        finally:
            connection.close()

    def composer(self, composer_id: str) -> dict[str, Any] | None:
        with self.reader() as reader:
            return reader.composer(composer_id)

    def bubbles(self, composer_id: str) -> list[CursorBubbleRecord]:
        with self.reader() as reader:
            return reader.bubbles(composer_id)

    def transcript_bubbles(self, composer_id: str) -> list[CursorBubbleRecord]:
        with self.reader() as reader:
            return reader.transcript_bubbles(composer_id)

    def _default_user_root(self) -> Path:
        home = Path.home()
        if os.name == "nt":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "Cursor" / "User"
            return home / "AppData" / "Roaming" / "Cursor" / "User"
        if sys.platform.startswith("darwin"):
            return home / "Library" / "Application Support" / "Cursor" / "User"
        return home / ".config" / "Cursor" / "User"

    def _missing_database_error(self) -> DiagnosticError:
        return source_missing(
            "Cursor global database is missing",
            missing_path=self.database_path(),
            searched_roots=[root.render() for root in self.search_roots()],
            next_steps=(
                i18n.t(Keys.DIAG_STEP_CURSOR_DB_EXISTS),
                i18n.t(Keys.DIAG_STEP_CURSOR_LIST_TO_CHECK),
            ),
        )
