"""
测试配置和共享 fixtures
"""

import json
import os
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Path:
    """创建模拟数据库文件"""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 创建 session 表
    cursor.execute("""
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            title TEXT,
            time_created INTEGER,
            time_updated INTEGER,
            slug TEXT,
            directory TEXT,
            version INTEGER,
            summary_files TEXT
        )
    """)

    # 创建 message 表
    cursor.execute("""
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            time_created INTEGER,
            data TEXT
        )
    """)

    # 创建 part 表
    cursor.execute("""
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT,
            time_created INTEGER,
            data TEXT
        )
    """)

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_session() -> dict:
    """返回示例会话数据"""
    return {
        "id": "test-session-001",
        "title": "测试会话标题",
        "time_created": 1704067200000,  # 2024-01-01 00:00:00 in ms
        "time_updated": 1704153600000,
        "slug": "test-session",
        "directory": "/test/dir",
        "version": 1,
        "summary_files": "file1.py,file2.py",
        "created_formatted": "2024-01-01 00:00:00",
    }


@pytest.fixture
def sample_sessions() -> list[dict]:
    """返回多个示例会话数据"""
    return [
        {
            "id": "session-001",
            "title": "会话 1",
            "time_created": 1704067200000,
            "time_updated": 1704153600000,
            "slug": "session-1",
            "directory": "/test/dir1",
            "version": 1,
            "summary_files": "file1.py",
            "created_formatted": "2024-01-01 00:00:00",
        },
        {
            "id": "session-002",
            "title": "会话 2",
            "time_created": 1703980800000,
            "time_updated": 1704067200000,
            "slug": "session-2",
            "directory": "/test/dir2",
            "version": 1,
            "summary_files": "file2.py",
            "created_formatted": "2023-12-31 00:00:00",
        },
    ]


@pytest.fixture
def populated_db(mock_db_path: Path) -> Path:
    """创建填充了数据的模拟数据库"""
    conn = sqlite3.connect(mock_db_path)
    cursor = conn.cursor()

    # 插入会话
    cursor.execute(
        """
        INSERT INTO session (id, title, time_created, time_updated, slug, directory, version, summary_files)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        ("session-001", "测试会话", 1704067200000, 1704153600000, "test", "/test", 1, "file.py"),
    )

    # 插入消息
    msg_data = {
        "role": "user",
        "agent": "claude",
        "mode": "chat",
        "modelID": "claude-3-opus",
        "providerID": "anthropic",
        "time": {"completed": 1704067300000},
        "tokens": {"input": 100, "output": 50},
        "cost": 0.001,
    }
    cursor.execute(
        """
        INSERT INTO message (id, session_id, time_created, data)
        VALUES (?, ?, ?, ?)
    """,
        ("msg-001", "session-001", 1704067200000, json.dumps(msg_data)),
    )

    # 插入 part
    part_data = {"type": "text", "text": "Hello World"}
    cursor.execute(
        """
        INSERT INTO part (id, message_id, time_created, data)
        VALUES (?, ?, ?, ?)
    """,
        ("part-001", "msg-001", 1704067200000, json.dumps(part_data)),
    )

    conn.commit()
    conn.close()
    return mock_db_path
