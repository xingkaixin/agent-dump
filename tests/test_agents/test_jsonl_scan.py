"""测试 agents/jsonl_scan.py 模块"""

from datetime import datetime, timedelta, timezone
import os

from agent_dump.agents.jsonl_scan import file_modified_since


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
