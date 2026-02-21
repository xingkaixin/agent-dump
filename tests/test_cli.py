"""
测试 cli.py 模块
"""

from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.cli import main


def get_current_timestamp_ms() -> int:
    """获取当前时间的毫秒时间戳"""
    return int(datetime.now().timestamp() * 1000)


class TestCliMain:
    """测试 CLI main 函数"""

    def test_list_mode(self, tmp_path: Path, capsys):
        """测试 --list 模式"""
        # 创建模拟数据库
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (
                id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT
            )
        """)
        now_ts = get_current_timestamp_ms()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Test Session", now_ts, now_ts, "slug", "/dir", 1, "files"),
        )
        conn.commit()
        conn.close()

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch("sys.argv", ["agent-dump", "--list", "--days", "7"]):
                main()

        captured = capsys.readouterr()
        assert "Test Session" in captured.out
        assert "Available sessions" in captured.out

    def test_export_by_ids(self, tmp_path: Path, capsys):
        """测试通过 --export 指定 ID 导出"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        cursor.execute("""
            CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)
        """)
        cursor.execute("""
            CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, time_created INTEGER, data TEXT)
        """)
        now_ts = get_current_timestamp_ms()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Test Session", now_ts, now_ts, "slug", "/dir", 1, "files"),
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "output"

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch("sys.argv", ["agent-dump", "--export", "s1", "--output", str(output_dir)]):
                main()

        captured = capsys.readouterr()
        assert "Successfully exported" in captured.out
        assert (output_dir / "opencode" / "s1.json").exists()

    def test_export_invalid_ids(self, tmp_path: Path, capsys):
        """测试导出无效的会话 ID"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        conn.commit()
        conn.close()

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch("sys.argv", ["agent-dump", "--export", "nonexistent"]):
                main()

        captured = capsys.readouterr()
        assert "No sessions found" in captured.out

    def test_database_not_found(self, capsys):
        """测试数据库未找到错误"""
        with mock.patch("agent_dump.cli.find_db_path", side_effect=FileNotFoundError("DB not found")):
            with mock.patch("sys.argv", ["agent-dump"]):
                main()

        captured = capsys.readouterr()
        assert "Error" in captured.out or "❌" in captured.out

    def test_no_sessions_found(self, tmp_path: Path, capsys):
        """测试没有找到会话"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        conn.commit()
        conn.close()

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch("sys.argv", ["agent-dump"]):
                main()

        captured = capsys.readouterr()
        assert "No sessions found" in captured.out or "Found 0 sessions" in captured.out

    def test_interactive_selection_no_selection(self, tmp_path: Path, capsys):
        """测试交互式选择但没有选择任何会话"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        now_ts = get_current_timestamp_ms()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Test Session", now_ts, now_ts, "slug", "/dir", 1, "files"),
        )
        conn.commit()
        conn.close()

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch("agent_dump.cli.select_sessions_interactive", return_value=[]):
                with mock.patch("sys.argv", ["agent-dump"]):
                    main()

        captured = capsys.readouterr()
        assert "No sessions selected" in captured.out or "Exiting" in captured.out


class TestCliArguments:
    """测试 CLI 参数解析"""

    def test_default_days(self, tmp_path: Path):
        """测试默认天数为 7"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        conn.commit()
        conn.close()

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch("agent_dump.cli.get_recent_sessions") as mock_get:
                mock_get.return_value = []
                with mock.patch("sys.argv", ["agent-dump"]):
                    main()

                mock_get.assert_called_once()
                assert mock_get.call_args[1]["days"] == 7

    def test_custom_days(self, tmp_path: Path):
        """测试自定义天数"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        conn.commit()
        conn.close()

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch("agent_dump.cli.get_recent_sessions") as mock_get:
                mock_get.return_value = []
                with mock.patch("sys.argv", ["agent-dump", "--days", "30"]):
                    main()

                mock_get.assert_called_once()
                assert mock_get.call_args[1]["days"] == 30

    def test_default_output_dir(self, tmp_path: Path):
        """测试默认输出目录"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        cursor.execute("""
            CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)
        """)
        cursor.execute("""
            CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, time_created INTEGER, data TEXT)
        """)
        now_ts = get_current_timestamp_ms()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Test", now_ts, now_ts, "slug", "/dir", 1, "files"),
        )
        conn.commit()
        conn.close()

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch(
                "agent_dump.cli.select_sessions_interactive",
                return_value=[
                    {
                        "id": "s1",
                        "title": "Test",
                        "slug": "slug",
                        "directory": "/dir",
                        "version": 1,
                        "time_created": now_ts,
                        "time_updated": now_ts,
                        "summary_files": "files",
                    }
                ],
            ):
                with mock.patch("sys.argv", ["agent-dump", "--export", "s1"]):
                    with mock.patch("pathlib.Path.mkdir"):  # 避免实际创建目录
                        main()

    def test_custom_output_dir(self, tmp_path: Path):
        """测试自定义输出目录"""
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT)
        """)
        cursor.execute("""
            CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)
        """)
        cursor.execute("""
            CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, time_created INTEGER, data TEXT)
        """)
        now_ts = get_current_timestamp_ms()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Test", now_ts, now_ts, "slug", "/dir", 1, "files"),
        )
        conn.commit()
        conn.close()

        custom_output = tmp_path / "custom_output"

        with mock.patch("agent_dump.cli.find_db_path", return_value=db_path):
            with mock.patch(
                "agent_dump.cli.select_sessions_interactive",
                return_value=[
                    {
                        "id": "s1",
                        "title": "Test",
                        "slug": "slug",
                        "directory": "/dir",
                        "version": 1,
                        "time_created": now_ts,
                        "time_updated": now_ts,
                        "summary_files": "files",
                    }
                ],
            ):
                with mock.patch("sys.argv", ["agent-dump", "--output", str(custom_output)]):
                    main()

        assert (custom_output / "opencode" / "s1.json").exists()
