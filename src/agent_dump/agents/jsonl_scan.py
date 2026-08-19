from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from agent_dump.coercion import safe_epoch_datetime
from agent_dump.i18n import Keys
from agent_dump.provider_diagnostics import ProviderDiagnostic

FULL_SCAN_BYTE_LIMIT = 256 * 1024
HEAD_SCAN_BYTE_LIMIT = 64 * 1024
TAIL_SCAN_BYTE_LIMIT = 64 * 1024
SKIPPED_LINE_SAMPLE_LIMIT = 5


def file_modified_since(file_path: Path, cutoff: datetime) -> bool:
    """Whether a session file may contain sessions created after the cutoff.

    Session JSONL files are append-only, so mtime >= created_at and files
    last modified before the cutoff can be skipped without opening them.
    """
    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        return True
    modified_at = safe_epoch_datetime(mtime, unit="s")
    return modified_at is None or modified_at >= cutoff


@dataclass(frozen=True)
class JsonlScanMetadata:
    first_record: dict[str, Any] | None
    head_records: list[dict[str, Any]]
    tail_record: dict[str, Any] | None
    scanned_all: bool
    nonempty_line_count: int | None
    # head 窗口里一个换行都没有：首记录本身比窗口还长，被当作不完整行丢弃了。
    # 与「文件为空」「首行不是 JSON 对象」是不同的事实，必须能分辨。
    oversized_head: bool = False

    @property
    def session_header(self) -> dict[str, Any] | None:
        """Header fields for this session, or None when the file holds no session.

        oversized_head 时返回空 dict 而不是 None：文件确实有会话内容，只是头部字段
        读不到。调用方既有的缺字段回退（mtime、目录名、文件名）正好适用，不必每个
        Provider 各写一遍「最小 Session」分支。靠首记录判定文件类型的 Provider
        （Pi 要求 type == "session"）仍会拒绝空 dict——那时无从确认文件类型。
        """
        if self.first_record is not None:
            return self.first_record
        return {} if self.oversized_head else None


def read_jsonl_scan_metadata(file_path: Path, *, head_line_limit: int) -> JsonlScanMetadata:
    file_size = file_path.stat().st_size
    if file_size == 0:
        return JsonlScanMetadata(
            first_record=None,
            head_records=[],
            tail_record=None,
            scanned_all=True,
            nonempty_line_count=0,
        )

    if file_size <= FULL_SCAN_BYTE_LIMIT:
        lines = _read_all_lines(file_path)
        records = _parse_jsonl_records(lines)
        return JsonlScanMetadata(
            first_record=_parse_json_object(lines[0]) if lines else None,
            head_records=records,
            tail_record=records[-1] if records else None,
            scanned_all=True,
            nonempty_line_count=len(lines),
        )

    head_lines, oversized_head = _read_complete_head_lines(file_path, max_lines=head_line_limit)
    head_records = _parse_jsonl_records(head_lines)
    tail_line = _read_last_complete_line(file_path)
    return JsonlScanMetadata(
        first_record=_parse_json_object(head_lines[0]) if head_lines else None,
        head_records=head_records,
        tail_record=_parse_json_object(tail_line) if tail_line is not None else None,
        scanned_all=False,
        nonempty_line_count=None,
        oversized_head=oversized_head,
    )


class JsonlObjectScan:
    """Iterate a JSONL file's root objects, remembering which lines were skipped.

    Provider store 由别的工具写入，一行完全可能是合法 JSON 却不是对象——`1`、`[]`、
    `"text"` 都是。裸 json.loads() 之后直接 .get() 会抛 AttributeError，一条坏记录
    就能中断整个 Session 的读取。这里只保证根是对象；嵌套 schema 仍由各 Provider
    自己解释，共享层不碰 Provider 私有结构。

    诊断按文件汇总而不是逐行打印：一个被截断或损坏的文件可能有成千上万条坏记录。
    """

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.skipped_count = 0
        self.skipped_line_samples: tuple[int, ...] = ()

    def _record_skipped_line(self, line_number: int) -> None:
        self.skipped_count += 1
        if len(self.skipped_line_samples) < SKIPPED_LINE_SAMPLE_LIMIT:
            self.skipped_line_samples += (line_number,)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for _, data in self.iter_with_line_numbers():
            yield data

    def iter_with_line_numbers(self) -> Iterator[tuple[int, dict[str, Any]]]:
        """Iterate root objects together with their one-based source line numbers.

        An unterminated malformed tail may still be an active append, so it is
        ignored without being reported as a damaged record.
        """
        with open(self.file_path, "rb") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.strip():
                    continue
                data = _parse_json_object(_decode_line(raw_line))
                if data is None:
                    if raw_line.endswith((b"\n", b"\r")):
                        self._record_skipped_line(line_number)
                    continue
                yield line_number, data


def parse_object_line(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line into its root object, or None when it is not one.

    与 JsonlObjectScan 同一个事实的单行入口，给已经持有行、且自己负责诊断的调用方用。
    """
    return _parse_json_object(line)


def parse_object_lines(lines: list[str]) -> list[dict[str, Any]]:
    """Parse already-read lines into root objects, dropping anything that is not one."""
    return _parse_jsonl_records(lines)


def skipped_records_diagnostic(scan: JsonlObjectScan) -> ProviderDiagnostic | None:
    """Build one aggregate diagnostic after a JSONL scan is exhausted."""
    if not scan.skipped_count:
        return None
    return ProviderDiagnostic(
        message_key=Keys.WARN_JSONL_RECORDS_SKIPPED,
        fields={
            "path": str(scan.file_path),
            "count": scan.skipped_count,
            "lines": ", ".join(str(line) for line in scan.skipped_line_samples),
        },
    )


def _read_all_lines(file_path: Path) -> list[str | None]:
    lines: list[str | None] = []
    with open(file_path, "rb") as f:
        for raw_line in f:
            if raw_line.strip():
                lines.append(_decode_line(raw_line))
    return lines


def _read_complete_head_lines(file_path: Path, *, max_lines: int) -> tuple[list[str | None], bool]:
    """Read complete head lines, and whether the window was one oversized record.

    第二个返回值只在窗口非空却一个换行都没有时为 True。窗口保持固定 64 KiB：
    改用 readline() 就会为任意长的首行做无界读取，正是这里要避免的。
    """
    with open(file_path, "rb") as f:
        chunk = f.read(HEAD_SCAN_BYTE_LIMIT)

    if not chunk:
        return [], False

    lines = chunk.splitlines()
    if not chunk.endswith((b"\n", b"\r")) and lines:
        lines = lines[:-1]
        if not lines:
            return [], True

    return [_decode_line(line) for line in lines[:max_lines] if line.strip()], False


def _read_last_complete_line(file_path: Path) -> str | None:
    """Read the last terminated nonempty line from a bounded tail window."""
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

    lines = chunk.splitlines()
    if chunk and not chunk.endswith((b"\n", b"\r")):
        lines = lines[:-1]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return None
    return _decode_line(lines[-1])


def _decode_line(line: bytes) -> str | None:
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _parse_json_object(line: str | None) -> dict[str, Any] | None:
    if line is None:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_jsonl_records(lines: Iterable[str | None]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in lines:
        data = _parse_json_object(line)
        if data is not None:
            records.append(data)
    return records


def parse_iso_timestamp_ms(value: Any) -> int:
    """Parse an ISO-8601 timestamp (with or without a `Z`) into epoch milliseconds.

    没有时区信息的时间戳按 UTC 解释。直接对 naive datetime 调 .timestamp() 会让 Python
    按**本机时区**解释它，同一份会话数据在不同时区的机器上会得到相差数小时的时间戳；
    codex 与 claudecode 之前各自的实现都有这个问题，pi 的版本是对的。
    """
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)
