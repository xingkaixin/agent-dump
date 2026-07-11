from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

FULL_SCAN_BYTE_LIMIT = 256 * 1024
HEAD_SCAN_BYTE_LIMIT = 64 * 1024
TAIL_SCAN_BYTE_LIMIT = 64 * 1024


def file_modified_since(file_path: Path, cutoff: datetime) -> bool:
    """Whether a session file may contain sessions created after the cutoff.

    Session JSONL files are append-only, so mtime >= created_at and files
    last modified before the cutoff can be skipped without opening them.
    """
    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        return True
    return datetime.fromtimestamp(mtime, tz=timezone.utc) >= cutoff


@dataclass(frozen=True)
class JsonlScanMetadata:
    first_record: dict[str, Any] | None
    head_records: list[dict[str, Any]]
    tail_record: dict[str, Any] | None
    scanned_all: bool


def read_jsonl_scan_metadata(file_path: Path, *, head_line_limit: int) -> JsonlScanMetadata:
    file_size = file_path.stat().st_size
    if file_size == 0:
        return JsonlScanMetadata(first_record=None, head_records=[], tail_record=None, scanned_all=True)

    if file_size <= FULL_SCAN_BYTE_LIMIT:
        lines = _read_all_lines(file_path)
        records = _parse_jsonl_records(lines)
        return JsonlScanMetadata(
            first_record=_parse_json_object(lines[0]) if lines else None,
            head_records=records,
            tail_record=records[-1] if records else None,
            scanned_all=True,
        )

    head_lines = _read_complete_head_lines(file_path, max_lines=head_line_limit)
    head_records = _parse_jsonl_records(head_lines)
    tail_line = _read_last_complete_line(file_path)
    return JsonlScanMetadata(
        first_record=_parse_json_object(head_lines[0]) if head_lines else None,
        head_records=head_records,
        tail_record=_parse_json_object(tail_line) if tail_line is not None else None,
        scanned_all=False,
    )


def _read_all_lines(file_path: Path) -> list[str]:
    lines: list[str] = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                lines.append(line)
    return lines


def _read_complete_head_lines(file_path: Path, *, max_lines: int) -> list[str]:
    with open(file_path, "rb") as f:
        chunk = f.read(HEAD_SCAN_BYTE_LIMIT)

    if not chunk:
        return []

    lines = chunk.splitlines()
    if not chunk.endswith((b"\n", b"\r")) and lines:
        lines = lines[:-1]

    return [_decode_line(line) for line in lines[:max_lines] if line.strip()]


def _read_last_complete_line(file_path: Path) -> str | None:
    file_size = file_path.stat().st_size
    offset = max(0, file_size - TAIL_SCAN_BYTE_LIMIT)

    with open(file_path, "rb") as f:
        f.seek(offset)
        chunk = f.read(TAIL_SCAN_BYTE_LIMIT)

    if not chunk:
        return None

    if offset > 0:
        _, separator, chunk = chunk.partition(b"\n")
        if not separator:
            return None

    lines = [line for line in chunk.splitlines() if line.strip()]
    if not lines:
        return None
    return _decode_line(lines[-1])


def _decode_line(line: bytes) -> str:
    return line.decode("utf-8", errors="ignore")


def _parse_json_object(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_jsonl_records(lines: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in lines:
        data = _parse_json_object(line)
        if data is not None:
            records.append(data)
    return records
