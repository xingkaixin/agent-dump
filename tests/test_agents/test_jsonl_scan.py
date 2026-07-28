"""测试 agents/jsonl_scan.py 模块"""

import builtins
from datetime import datetime, timedelta, timezone
import json
import os
from unittest import mock

from agent_dump.agents.jsonl_scan import (
    FULL_SCAN_BYTE_LIMIT,
    HEAD_SCAN_BYTE_LIMIT,
    TAIL_SCAN_BYTE_LIMIT,
    file_modified_since,
    read_jsonl_scan_metadata,
)


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


def _record(size: int, **extra) -> str:
    payload = {"timestamp": "2026-01-01T00:00:00Z", **extra}
    filler = size - len(json.dumps({**payload, "pad": ""}))
    return json.dumps({**payload, "pad": "x" * max(filler, 0)})


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
