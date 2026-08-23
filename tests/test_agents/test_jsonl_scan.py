"""测试 agents/jsonl_scan.py 模块"""

import builtins
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_dump.agents.jsonl_scan import (
    FULL_SCAN_BYTE_LIMIT,
    HEAD_SCAN_BYTE_LIMIT,
    TAIL_SCAN_BYTE_LIMIT,
    JsonlObjectScan,
    file_modified_since,
    parse_object_line,
    read_jsonl_scan_metadata,
    skipped_records_diagnostic,
)
from agent_dump.diagnostics import render_recoverable_diagnostic


class TestFileModifiedSince:
    def test_recent_file_passes_cutoff(self, tmp_path):
        """测试新写入的文件通过 cutoff 判定"""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text("{}\n")

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        assert file_modified_since(file_path, cutoff) is True

    def test_old_file_is_skipped(self, tmp_path):
        """测试 mtime 早于 cutoff 的文件被跳过"""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text("{}\n")
        old_time = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
        os.utime(file_path, (old_time, old_time))

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        assert file_modified_since(file_path, cutoff) is False

    def test_stat_failure_keeps_file(self, tmp_path):
        """测试 stat 失败时保守放行"""
        missing = tmp_path / "missing.jsonl"

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        assert file_modified_since(missing, cutoff) is True

    def test_unrepresentable_mtime_keeps_file_without_raising(self, tmp_path):
        file_path = tmp_path / "session.jsonl"
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        with mock.patch.object(Path, "stat", return_value=SimpleNamespace(st_mtime=10**400)):
            assert file_modified_since(file_path, cutoff) is True


def _record(size: int, **extra) -> str:
    payload = {"timestamp": "2026-01-01T00:00:00Z", **extra}
    filler = size - len(json.dumps({**payload, "pad": ""}))
    return json.dumps({**payload, "pad": "x" * max(filler, 0)})


class TestNonemptyLineCount:
    def test_small_scan_counts_every_nonempty_source_line(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text('{"n": 1}\n\nnot-json\n[]\n', encoding="utf-8")

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.scanned_all is True
        assert scan.nonempty_line_count == 3

    def test_large_scan_marks_the_line_count_unknown(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text(_record(FULL_SCAN_BYTE_LIMIT + 1024) + "\n", encoding="utf-8")

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.scanned_all is False
        assert scan.nonempty_line_count is None

    def test_small_scan_tolerates_an_invalid_utf8_record(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_bytes(b'{"n": 1}\n{"text": "\xff"}\n{"n": 2}\n')

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.scanned_all is True
        assert scan.nonempty_line_count == 3
        assert scan.first_record == {"n": 1}
        assert scan.head_records == [{"n": 1}, {"n": 2}]
        assert scan.tail_record == {"n": 2}


class TestActiveTailRecord:
    def test_incomplete_tail_does_not_hide_the_last_complete_record(self, tmp_path):
        file_path = tmp_path / "active.jsonl"
        file_path.write_text(
            _record(FULL_SCAN_BYTE_LIMIT + 1024, marker="head")
            + "\n"
            + _record(200, marker="last-complete")
            + "\n"
            + '{"marker":"partial"',
            encoding="utf-8",
        )

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.scanned_all is False
        assert scan.tail_record is not None
        assert scan.tail_record["marker"] == "last-complete"

    def test_unterminated_valid_json_is_not_treated_as_committed(self, tmp_path):
        file_path = tmp_path / "active.jsonl"
        file_path.write_text(
            _record(FULL_SCAN_BYTE_LIMIT + 1024, marker="head")
            + "\n"
            + _record(200, marker="last-complete")
            + "\n"
            + _record(200, marker="not-committed"),
            encoding="utf-8",
        )

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.tail_record is not None
        assert scan.tail_record["marker"] == "last-complete"

    def test_terminated_tail_remains_the_latest_record(self, tmp_path):
        file_path = tmp_path / "complete.jsonl"
        file_path.write_text(
            _record(FULL_SCAN_BYTE_LIMIT + 1024, marker="head") + "\n" + _record(200, marker="latest") + "\n",
            encoding="utf-8",
        )

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.tail_record is not None
        assert scan.tail_record["marker"] == "latest"


class TestOversizedHeadRecord:
    """AD-159：首记录超过 head 窗口不得让整个 Session 消失。"""

    def test_small_first_record_is_parsed_normally(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text(_record(200, marker="first") + "\n" + _record(FULL_SCAN_BYTE_LIMIT, marker="rest") + "\n")

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.oversized_head is False
        assert scan.first_record is not None
        assert scan.first_record["marker"] == "first"
        assert scan.session_header is scan.first_record

    def test_first_record_just_under_the_head_window(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text(
            _record(HEAD_SCAN_BYTE_LIMIT - 100, marker="first") + "\n" + _record(FULL_SCAN_BYTE_LIMIT) + "\n"
        )

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.oversized_head is False
        assert scan.first_record is not None
        assert scan.first_record["marker"] == "first"

    def test_first_record_larger_than_the_head_window(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text(_record(HEAD_SCAN_BYTE_LIMIT + 100) + "\n" + _record(FULL_SCAN_BYTE_LIMIT) + "\n")

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.oversized_head is True
        assert scan.first_record is None
        assert scan.session_header == {}, "文件确实有内容，调用方应拿到可回退的空 header"

    def test_file_holding_only_one_oversized_record(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text(_record(FULL_SCAN_BYTE_LIMIT + 1024) + "\n")

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.oversized_head is True
        assert scan.session_header == {}

    def test_empty_file_is_not_oversized(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text("")

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.oversized_head is False
        assert scan.session_header is None, "空文件没有会话，不得被当成可回退的 header"
        assert scan.nonempty_line_count == 0

    def test_malformed_large_file_is_not_treated_as_a_session(self, tmp_path):
        """有换行但首行不是 JSON 对象：既有行为不变，仍视为无会话。"""
        file_path = tmp_path / "s.jsonl"
        file_path.write_text("not json\n" + "y" * FULL_SCAN_BYTE_LIMIT + "\n")

        scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.oversized_head is False
        assert scan.session_header is None

    def test_scan_stays_bounded_for_a_multi_megabyte_single_line(self, tmp_path):
        """不得为拿到首行而无界读取。"""
        file_path = tmp_path / "s.jsonl"
        file_path.write_text(_record(4 * 1024 * 1024) + "\n" + _record(200) + "\n")

        read_bytes = [0]
        real_open = builtins.open

        def counting_open(*args, **kwargs):
            handle = real_open(*args, **kwargs)
            real_read = handle.read

            def read(size=-1):
                data = real_read(size)
                read_bytes[0] += len(data)
                return data

            handle.read = read
            return handle

        with mock.patch.object(builtins, "open", counting_open):
            scan = read_jsonl_scan_metadata(file_path, head_line_limit=20)

        assert scan.oversized_head is True
        assert read_bytes[0] <= HEAD_SCAN_BYTE_LIMIT + TAIL_SCAN_BYTE_LIMIT, (
            f"读取了 {read_bytes[0]} 字节，超出 head+tail 窗口"
        )


class TestJsonlObjectScan:
    """AD-160：合法但非对象的记录只能被跳过，不能中断整个文件的读取。"""

    def test_non_object_roots_are_skipped_with_line_numbers(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text(
            '{"n": 1}\n1\n[]\n"text"\nnull\ntrue\n{"n": 2}\n',
            encoding="utf-8",
        )

        scan = JsonlObjectScan(file_path)

        assert list(scan) == [{"n": 1}, {"n": 2}], "坏记录前后的对象都必须保留"
        assert scan.skipped_count == 5
        assert scan.skipped_line_samples == (2, 3, 4, 5, 6)

    def test_malformed_json_is_skipped_too(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text('{"n": 1}\n{not json\n{"n": 2}\n', encoding="utf-8")

        scan = JsonlObjectScan(file_path)

        assert list(scan) == [{"n": 1}, {"n": 2}]
        assert scan.skipped_count == 1
        assert scan.skipped_line_samples == (2,)

    def test_invalid_utf8_is_skipped_without_losing_surrounding_records(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_bytes(b'{"n": 1}\n{"text": "\xff"}\n{"n": 2}\n')

        scan = JsonlObjectScan(file_path)

        assert list(scan.iter_with_line_numbers()) == [(1, {"n": 1}), (3, {"n": 2})]
        assert scan.skipped_count == 1
        assert scan.skipped_line_samples == (2,)

    def test_unterminated_malformed_tail_is_treated_as_an_active_append(self, tmp_path):
        file_path = tmp_path / "active.jsonl"
        file_path.write_bytes(b'{"n": 1}\n{"n":')

        scan = JsonlObjectScan(file_path)

        assert list(scan) == [{"n": 1}]
        assert scan.skipped_count == 0
        assert scan.skipped_line_samples == ()

    def test_unterminated_valid_tail_is_still_read(self, tmp_path):
        file_path = tmp_path / "complete.jsonl"
        file_path.write_bytes(b'{"n": 1}\n{"n": 2}')

        scan = JsonlObjectScan(file_path)

        assert list(scan) == [{"n": 1}, {"n": 2}]
        assert scan.skipped_count == 0

    def test_blank_lines_are_not_counted_as_skipped(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text('{"n": 1}\n\n   \n{"n": 2}\n', encoding="utf-8")

        scan = JsonlObjectScan(file_path)

        assert list(scan) == [{"n": 1}, {"n": 2}]
        assert scan.skipped_count == 0
        assert scan.skipped_line_samples == ()

    def test_skipped_record_state_is_bounded_independently_of_failure_count(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text("1\n" * 10_000 + '{"n": 1}\n', encoding="utf-8")

        scan = JsonlObjectScan(file_path)

        assert list(scan) == [{"n": 1}]
        assert scan.skipped_count == 10_000
        assert scan.skipped_line_samples == (1, 2, 3, 4, 5)
        assert all(not isinstance(value, list) for value in vars(scan).values())

    def test_clean_file_has_no_diagnostic(self, tmp_path):
        file_path = tmp_path / "s.jsonl"
        file_path.write_text('{"n": 1}\n', encoding="utf-8")

        scan = JsonlObjectScan(file_path)
        list(scan)

        assert skipped_records_diagnostic(scan) is None

    def test_diagnostic_renders_as_one_sanitized_line_without_a_traceback(self, tmp_path):
        file_path = tmp_path / "s\x1b[31m.jsonl"
        file_path.write_text("1\n" * 50, encoding="utf-8")

        scan = JsonlObjectScan(file_path)
        list(scan)
        diagnostic = skipped_records_diagnostic(scan)

        assert diagnostic is not None
        rendered = render_recoverable_diagnostic(diagnostic)
        assert "\n" not in rendered, "成千上万条坏记录只能产生一条诊断"
        assert "50" in rendered
        assert "\x1b" not in rendered, "路径来自不可信输入，必须净化后才进终端"
        assert "Traceback" not in rendered

    def test_parse_object_line_rejects_non_objects(self, tmp_path):
        assert parse_object_line('{"n": 1}') == {"n": 1}
        assert parse_object_line("1") is None
        assert parse_object_line("[]") is None
        assert parse_object_line('"text"') is None
        assert parse_object_line("{bad") is None
