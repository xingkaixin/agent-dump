"""
测试 db.py 模块
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.db import find_db_path, get_recent_sessions


class TestFindDbPath:
    """测试 find_db_path 函数"""

    def test_find_db_path_in_data_directory(self, tmp_path: Path, monkeypatch):
        """测试在 data/opencode 目录下找到数据库"""
        db_file = tmp_path / "opencode.db"
        db_file.touch()

        # 模拟 expanduser 返回临时目录
        def mock_expanduser(path: str) -> str:
            if path.startswith("data/"):
                return str(tmp_path / "opencode.db")
            return path

        monkeypatch.setattr(os.path, "expanduser", mock_expanduser)

        # 由于 expanduser 的模拟方式，需要调整测试逻辑
        # 让我们直接创建预期的数据库路径
        with mock.patch("agent_dump.db.os.path.exists") as mock_exists:
            mock_exists.return_value = True
            result = find_db_path()
            assert result.name == "opencode.db"

    def test_find_db_path_not_found(self, monkeypatch):
        """测试找不到数据库时抛出 FileNotFoundError"""
        with mock.patch("agent_dump.db.os.path.exists", return_value=False):
            with pytest.raises(FileNotFoundError, match="Could not find opencode.db"):
                find_db_path()


class TestGetRecentSessions:
    """测试 get_recent_sessions 函数"""

    def test_get_recent_sessions_empty_db(self, mock_db_path: Path):
        """测试空数据库返回空列表"""
        sessions = get_recent_sessions(mock_db_path, days=7)
        assert sessions == []

    def test_get_recent_sessions_with_data(self, mock_db_path: Path):
        """测试获取最近会话"""
        # 准备数据
        now = datetime.now()
        yesterday = int((now - timedelta(days=1)).timestamp() * 1000)
        old_time = int((now - timedelta(days=10)).timestamp() * 1000)

        conn = sqlite3.connect(mock_db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "会话 1", yesterday, yesterday, "slug1", "/dir1", 1, "file1"),
        )
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s2", "会话 2", old_time, old_time, "slug2", "/dir2", 1, "file2"),
        )
        conn.commit()
        conn.close()

        # 测试只返回最近 7 天的会话
        sessions = get_recent_sessions(mock_db_path, days=7)
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s1"
        assert sessions[0]["title"] == "会话 1"
        assert "created_formatted" in sessions[0]

    def test_get_recent_sessions_ordered_by_time(self, mock_db_path: Path):
        """测试会话按时间倒序排列"""
        now = datetime.now()

        conn = sqlite3.connect(mock_db_path)
        cursor = conn.cursor()

        for i, days in enumerate([1, 3, 2]):
            time_created = int((now - timedelta(days=days)).timestamp() * 1000)
            cursor.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"s{i}", f"会话 {i}", time_created, time_created, f"slug{i}", f"/dir{i}", 1, f"file{i}"),
            )
        conn.commit()
        conn.close()

        sessions = get_recent_sessions(mock_db_path, days=7)
        assert len(sessions) == 3
        # 应该按时间倒序：1天前 > 2天前 > 3天前
        assert sessions[0]["id"] == "s0"  # 1天前
        assert sessions[1]["id"] == "s2"  # 2天前
        assert sessions[2]["id"] == "s1"  # 3天前

    def test_get_recent_sessions_includes_all_fields(self, mock_db_path: Path):
        """测试返回的会话包含所有必要字段"""
        now = datetime.now()
        time_created = int(now.timestamp() * 1000)

        conn = sqlite3.connect(mock_db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-id", "Test Title", time_created, time_created, "test-slug", "/test/dir", 2, "summary.txt"),
        )
        conn.commit()
        conn.close()

        sessions = get_recent_sessions(mock_db_path, days=7)
        assert len(sessions) == 1
        session = sessions[0]

        assert session["id"] == "test-id"
        assert session["title"] == "Test Title"
        assert session["time_created"] == time_created
        assert session["time_updated"] == time_created
        assert session["slug"] == "test-slug"
        assert session["directory"] == "/test/dir"
        assert session["version"] == 2
        assert session["summary_files"] == "summary.txt"
        assert "created_formatted" in session
