"""
测试 exporter.py 模块
"""

import json
import sqlite3
from pathlib import Path

import pytest

from agent_dump.exporter import export_session, export_sessions


class TestExportSession:
    """测试 export_session 函数"""

    def test_export_session_creates_json_file(self, populated_db: Path, tmp_path: Path):
        """测试导出会话创建 JSON 文件"""
        session = {
            "id": "session-001",
            "title": "测试会话",
            "slug": "test",
            "directory": "/test",
            "version": 1,
            "time_created": 1704067200000,
            "time_updated": 1704153600000,
            "summary_files": "file.py",
        }

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = export_session(populated_db, session, output_dir)

        assert result.exists()
        assert result.name == "session-001.json"
        assert result.parent == output_dir

    def test_export_session_content_structure(self, populated_db: Path, tmp_path: Path):
        """测试导出文件的内容结构"""
        session = {
            "id": "session-001",
            "title": "测试会话",
            "slug": "test",
            "directory": "/test",
            "version": 1,
            "time_created": 1704067200000,
            "time_updated": 1704153600000,
            "summary_files": "file.py",
        }

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_session(populated_db, session, output_dir)

        with open(output_dir / "session-001.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        # 验证基本字段
        assert data["id"] == "session-001"
        assert data["title"] == "测试会话"
        assert data["slug"] == "test"
        assert data["directory"] == "/test"
        assert data["version"] == 1
        assert data["time_created"] == 1704067200000
        assert data["time_updated"] == 1704153600000
        assert data["summary_files"] == "file.py"

        # 验证统计字段
        assert "stats" in data
        assert "total_cost" in data["stats"]
        assert "total_input_tokens" in data["stats"]
        assert "total_output_tokens" in data["stats"]
        assert "message_count" in data["stats"]

        # 验证消息数组
        assert "messages" in data
        assert isinstance(data["messages"], list)

    def test_export_session_with_messages(self, populated_db: Path, tmp_path: Path):
        """测试导出包含消息的会话"""
        session = {
            "id": "session-001",
            "title": "测试会话",
            "slug": "test",
            "directory": "/test",
            "version": 1,
            "time_created": 1704067200000,
            "time_updated": 1704153600000,
            "summary_files": "file.py",
        }

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_session(populated_db, session, output_dir)

        with open(output_dir / "session-001.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data["messages"]) == 1
        msg = data["messages"][0]
        assert msg["id"] == "msg-001"
        assert msg["role"] == "user"
        assert msg["agent"] == "claude"
        assert msg["model"] == "claude-3-opus"
        assert msg["provider"] == "anthropic"

        # 验证统计信息
        assert data["stats"]["message_count"] == 1
        assert data["stats"]["total_cost"] == 0.001
        assert data["stats"]["total_input_tokens"] == 100
        assert data["stats"]["total_output_tokens"] == 50

    def test_export_session_with_parts(self, populated_db: Path, tmp_path: Path):
        """测试导出包含 parts 的消息"""
        session = {
            "id": "session-001",
            "title": "测试会话",
            "slug": "test",
            "directory": "/test",
            "version": 1,
            "time_created": 1704067200000,
            "time_updated": 1704153600000,
            "summary_files": "file.py",
        }

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_session(populated_db, session, output_dir)

        with open(output_dir / "session-001.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        msg = data["messages"][0]
        assert len(msg["parts"]) == 1
        part = msg["parts"][0]
        assert part["type"] == "text"
        assert part["text"] == "Hello World"

    def test_export_session_different_part_types(self, tmp_path: Path):
        """测试导出不同类型的 parts"""
        # 创建带多种 part 类型的数据库
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 创建表
        cursor.execute("""
            CREATE TABLE session (
                id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version INTEGER, summary_files TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE message (
                id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY, message_id TEXT, time_created INTEGER, data TEXT
            )
        """)

        # 插入数据
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "Test", 1000, 1000, "slug", "/dir", 1, "files"),
        )
        cursor.execute("INSERT INTO message VALUES (?, ?, ?, ?)", ("m1", "s1", 1000, json.dumps({"role": "assistant"})))

        # 不同类型的 parts
        parts_data = [
            ("p1", "m1", 1000, json.dumps({"type": "text", "text": "文本内容"})),
            ("p2", "m1", 1001, json.dumps({"type": "reasoning", "text": "推理过程"})),
            (
                "p3",
                "m1",
                1002,
                json.dumps({"type": "tool", "tool": "read", "callID": "c1", "title": "读取文件", "state": {}}),
            ),
            ("p4", "m1", 1003, json.dumps({"type": "step-start", "reason": "开始步骤", "tokens": {}, "cost": 0})),
            ("p5", "m1", 1004, json.dumps({"type": "step-finish", "reason": "完成步骤", "tokens": {}, "cost": 0})),
        ]
        cursor.executemany("INSERT INTO part VALUES (?, ?, ?, ?)", parts_data)
        conn.commit()
        conn.close()

        session = {
            "id": "s1",
            "title": "Test",
            "slug": "slug",
            "directory": "/dir",
            "version": 1,
            "time_created": 1000,
            "time_updated": 1000,
            "summary_files": "files",
        }

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        export_session(db_path, session, output_dir)

        with open(output_dir / "s1.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        parts = data["messages"][0]["parts"]
        assert len(parts) == 5

        # 验证各种 part 类型
        assert parts[0]["type"] == "text" and parts[0]["text"] == "文本内容"
        assert parts[1]["type"] == "reasoning" and parts[1]["text"] == "推理过程"
        assert parts[2]["type"] == "tool" and parts[2]["tool"] == "read"
        assert parts[3]["type"] == "step-start" and parts[3]["reason"] == "开始步骤"
        assert parts[4]["type"] == "step-finish" and parts[4]["reason"] == "完成步骤"


class TestExportSessions:
    """测试 export_sessions 函数"""

    def test_export_multiple_sessions(self, populated_db: Path, tmp_path: Path):
        """测试批量导出多个会话"""
        # 添加第二个会话
        conn = sqlite3.connect(populated_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-002", "第二个会话", 1704067200000, 1704153600000, "test2", "/test2", 1, "file2.py"),
        )
        conn.commit()
        conn.close()

        sessions = [
            {
                "id": "session-001",
                "title": "测试会话",
                "slug": "test",
                "directory": "/test",
                "version": 1,
                "time_created": 1704067200000,
                "time_updated": 1704153600000,
                "summary_files": "file.py",
            },
            {
                "id": "session-002",
                "title": "第二个会话",
                "slug": "test2",
                "directory": "/test2",
                "version": 1,
                "time_created": 1704067200000,
                "time_updated": 1704153600000,
                "summary_files": "file2.py",
            },
        ]

        output_dir = tmp_path / "output"
        results = export_sessions(populated_db, sessions, output_dir)

        assert len(results) == 2
        assert all(r.exists() for r in results)
        assert (output_dir / "session-001.json").exists()
        assert (output_dir / "session-002.json").exists()

    def test_export_creates_output_directory(self, populated_db: Path, tmp_path: Path):
        """测试自动创建输出目录"""
        session = {
            "id": "session-001",
            "title": "测试会话",
            "slug": "test",
            "directory": "/test",
            "version": 1,
            "time_created": 1704067200000,
            "time_updated": 1704153600000,
            "summary_files": "file.py",
        }

        output_dir = tmp_path / "nested" / "output" / "dir"
        # 目录不应该预先存在
        assert not output_dir.exists()

        export_sessions(populated_db, [session], output_dir)

        assert output_dir.exists()
        assert (output_dir / "session-001.json").exists()

    def test_export_empty_sessions_list(self, populated_db: Path, tmp_path: Path, capsys):
        """测试导出空会话列表"""
        output_dir = tmp_path / "output"
        results = export_sessions(populated_db, [], output_dir)

        assert results == []
        assert output_dir.exists()  # 目录仍然会被创建
