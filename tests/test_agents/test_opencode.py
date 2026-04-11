"""
测试 agents/opencode.py 模块
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.paths import ProviderRoots


class TestOpenCodeAgent:
    """测试 OpenCodeAgent 类"""

    def test_init(self):
        """测试初始化"""
        agent = OpenCodeAgent()
        assert agent.name == "opencode"
        assert agent.display_name == "OpenCode"
        assert agent.db_path is None

    def test_find_db_path_not_found(self, tmp_path):
        """测试找不到数据库"""
        agent = OpenCodeAgent()

        with mock.patch.object(Path, "exists", return_value=False):
            result = agent._find_db_path()

        assert result is None

    def test_find_db_path_home_directory(self, tmp_path):
        """测试在用户目录找到数据库"""
        agent = OpenCodeAgent()
        opencode_root = tmp_path / ".local" / "share" / "opencode"
        opencode_root.mkdir(parents=True)
        db_path = opencode_root / "opencode.db"
        db_path.touch()

        roots = ProviderRoots(
            codex_root=tmp_path / ".codex",
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / ".kimi",
            opencode_root=opencode_root,
        )

        with mock.patch("agent_dump.agents.opencode.ProviderRoots.from_env_or_home", return_value=roots):
            result = agent._find_db_path()

        assert result == db_path

    def test_find_db_path_uses_windows_data_root(self, tmp_path):
        """测试使用 Windows 风格数据目录"""
        agent = OpenCodeAgent()
        opencode_root = tmp_path / "LocalAppData" / "opencode"
        opencode_root.mkdir(parents=True)
        db_path = opencode_root / "opencode.db"
        db_path.touch()

        roots = ProviderRoots(
            codex_root=tmp_path / ".codex",
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / ".kimi",
            opencode_root=opencode_root,
        )

        with mock.patch("agent_dump.agents.opencode.ProviderRoots.from_env_or_home", return_value=roots):
            result = agent._find_db_path()

        assert result == db_path

    def test_find_db_path_falls_back_to_local_dev(self, monkeypatch, tmp_path):
        """测试回退到本地开发数据库路径"""
        agent = OpenCodeAgent()
        monkeypatch.chdir(tmp_path)
        local_db_path = tmp_path / "data" / "opencode" / "opencode.db"
        local_db_path.parent.mkdir(parents=True)
        local_db_path.touch()

        roots = ProviderRoots(
            codex_root=tmp_path / ".codex",
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / ".kimi",
            opencode_root=tmp_path / "missing-opencode-root",
        )

        with mock.patch("agent_dump.agents.opencode.ProviderRoots.from_env_or_home", return_value=roots):
            result = agent._find_db_path()

        assert result == Path("data/opencode/opencode.db")

    def test_is_available_false(self):
        """测试数据库不存在时返回 False"""
        agent = OpenCodeAgent()

        with mock.patch.object(agent, "_find_db_path", return_value=None):
            result = agent.is_available()

        assert result is False
        assert agent.db_path is None

    def test_is_available_true(self, tmp_path):
        """测试数据库存在时返回 True"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"
        db_path.touch()

        with mock.patch.object(agent, "_find_db_path", return_value=db_path):
            result = agent.is_available()

        assert result is True
        assert agent.db_path == db_path

    def test_scan_no_db(self):
        """测试没有数据库时 scan 返回空列表"""
        agent = OpenCodeAgent()
        agent.db_path = None

        result = agent.scan()

        assert result == []

    def test_get_sessions_no_db(self):
        """测试没有数据库时 get_sessions 返回空列表"""
        agent = OpenCodeAgent()
        agent.db_path = None

        result = agent.get_sessions(days=7)

        assert result == []

    def test_get_sessions_with_data(self, tmp_path):
        """测试从数据库获取会话"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"

        # 创建测试数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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

        # 插入测试数据
        now = int(datetime.now().timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-001", "Test Session", now, now, "test", "/test", 1, "file.py"),
        )
        conn.commit()
        conn.close()

        agent.db_path = db_path
        result = agent.get_sessions(days=7)

        assert len(result) == 1
        assert result[0].id == "session-001"
        assert result[0].title == "Test Session"
        assert isinstance(result[0], Session)
        assert result[0].created_at.tzinfo == timezone.utc

    def test_get_sessions_parses_epoch_as_utc(self, tmp_path):
        """测试 epoch 毫秒会被解析为 UTC aware datetime"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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

        created_at = datetime(2025, 3, 5, 2, 0, tzinfo=timezone.utc)
        created_at_ms = int(created_at.timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-utc", "UTC Session", created_at_ms, created_at_ms, "utc", "/utc", 1, "utc.py"),
        )
        conn.commit()
        conn.close()

        agent.db_path = db_path

        result = agent.get_sessions(days=3650)

        assert len(result) == 1
        assert result[0].created_at == created_at

    def test_get_sessions_filtered_by_days(self, tmp_path):
        """测试按天数过滤会话"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"

        # 创建测试数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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

        # 插入新旧数据
        now = int(datetime.now().timestamp() * 1000)
        old_time = int((datetime.now() - timedelta(days=10)).timestamp() * 1000)

        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-001", "New Session", now, now, "new", "/new", 1, "new.py"),
        )
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-002", "Old Session", old_time, old_time, "old", "/old", 1, "old.py"),
        )
        conn.commit()
        conn.close()

        agent.db_path = db_path
        result = agent.get_sessions(days=7)

        assert len(result) == 1
        assert result[0].id == "session-001"

    def test_get_sessions_sorted_by_time(self, tmp_path):
        """测试会话按时间倒序排列"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"

        # 创建测试数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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

        # 插入多个会话
        now = int(datetime.now().timestamp() * 1000)
        yesterday = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-001", "Yesterday", yesterday, yesterday, "y", "/y", 1, "y.py"),
        )
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-002", "Today", now, now, "t", "/t", 1, "t.py"),
        )
        conn.commit()
        conn.close()

        agent.db_path = db_path
        result = agent.get_sessions(days=7)

        assert len(result) == 2
        assert result[0].id == "session-002"  # Today first
        assert result[1].id == "session-001"  # Yesterday second

    def test_get_sessions_null_title(self, tmp_path):
        """测试处理 null 标题"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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

        now = int(datetime.now().timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-001", None, now, now, "test", "/test", 1, "file.py"),
        )
        conn.commit()
        conn.close()

        agent.db_path = db_path
        result = agent.get_sessions(days=7)

        assert len(result) == 1
        assert result[0].title == "Untitled"

    def test_export_session_no_db(self, tmp_path):
        """测试没有数据库时导出报错"""
        agent = OpenCodeAgent()
        agent.db_path = None

        mock_session = mock.MagicMock()

        with pytest.raises(FileNotFoundError):
            agent.export_session(mock_session, tmp_path)

    def test_export_session_with_messages(self, tmp_path):
        """测试导出包含消息的会话"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # 创建测试数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 创建表
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
        cursor.execute("""
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)

        # 插入数据
        now = int(datetime.now().timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-001", "Test", now, now, "test", "/test", 1, "file.py"),
        )

        msg_data = json.dumps(
            {
                "role": "user",
                "agent": "claude",
                "mode": "chat",
                "modelID": "claude-3-opus",
                "providerID": "anthropic",
                "time": {"completed": now + 1000},
                "tokens": {"input": 100, "output": 50},
                "cost": 0.001,
            }
        )
        cursor.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("msg-001", "session-001", now, msg_data),
        )

        part_data = json.dumps({"type": "text", "text": "Hello"})
        cursor.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            ("part-001", "msg-001", now, part_data),
        )

        conn.commit()
        conn.close()

        agent.db_path = db_path

        # 创建 Session 对象
        session = Session(
            id="session-001",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=db_path,
            metadata={"slug": "test", "directory": "/test", "version": 1, "summary_files": "file.py"},
        )

        result = agent.export_session(session, output_dir)

        assert result.exists()
        assert result.name == "session-001.json"

        # 验证导出的 JSON
        with open(result) as f:
            data = json.load(f)

        assert data["id"] == "session-001"
        assert data["title"] == "Test Session"
        assert len(data["messages"]) == 1
        assert data["stats"]["message_count"] == 1
        assert data["stats"]["total_cost"] == 0.001
        assert data["stats"]["total_input_tokens"] == 100
        assert data["stats"]["total_output_tokens"] == 50

    def test_export_session_creates_missing_output_dir(self, tmp_path):
        """测试导出时会自动创建缺失的输出目录"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"
        output_dir = tmp_path / "nested" / "output"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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
        cursor.execute("""
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)

        now = int(datetime.now().timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-create-dir", "Test", now, now, "test", "/test", 1, "file.py"),
        )
        cursor.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            (
                "msg-001",
                "session-create-dir",
                now,
                json.dumps({"role": "user", "time": {}, "tokens": {}, "cost": 0}),
            ),
        )
        cursor.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            ("part-001", "msg-001", now, json.dumps({"type": "text", "text": "Hello"})),
        )
        conn.commit()
        conn.close()

        agent.db_path = db_path
        session = Session(
            id="session-create-dir",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=db_path,
            metadata={"slug": "test", "directory": "/test", "version": 1, "summary_files": "file.py"},
        )

        result = agent.export_session(session, output_dir)

        assert output_dir.exists()
        assert result.exists()

    def test_export_raw_session_matches_json_content(self, tmp_path):
        """测试 OpenCode raw 导出与 json 导出内容一致但文件名不同"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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
        cursor.execute("""
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)

        now = int(datetime.now().timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-raw", "Raw Test", now, now, "raw-test", "/test", 1, None),
        )
        cursor.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("msg-raw", "session-raw", now, json.dumps({"role": "user"})),
        )
        cursor.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            ("part-raw", "msg-raw", now, json.dumps({"type": "text", "text": "hello"})),
        )
        conn.commit()
        conn.close()

        agent.db_path = db_path
        session = Session(
            id="session-raw",
            title="Raw Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=db_path,
            metadata={"slug": "raw-test", "directory": "/test", "version": 1, "summary_files": None},
        )

        json_path = agent.export_session(session, output_dir)
        raw_path = agent.export_raw_session(session, output_dir)

        assert json_path.name == "session-raw.json"
        assert raw_path.name == "session-raw.raw.json"
        assert json.loads(json_path.read_text(encoding="utf-8")) == json.loads(raw_path.read_text(encoding="utf-8"))

    def test_get_session_head_extracts_model_message_count_and_subtargets(self, tmp_path):
        """测试 get_session_head 返回轻量摘要字段。"""
        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                title TEXT,
                time_created INTEGER,
                time_updated INTEGER,
                slug TEXT,
                directory TEXT,
                version INTEGER,
                summary_files TEXT
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            );
            """
        )
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        cur.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-head", "Head Session", now, now, "head", "/workspace/demo", 1, '["a.py","b.py"]'),
        )
        cur.executemany(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            [
                ("m1", "session-head", now, json.dumps({"role": "user", "modelID": "gpt-4.1"})),
                ("m2", "session-head", now + 1, json.dumps({"role": "assistant"})),
            ],
        )
        conn.commit()
        conn.close()

        agent = OpenCodeAgent()
        agent.db_path = db_path
        session = Session(
            id="session-head",
            title="Head Session",
            created_at=datetime.fromtimestamp(now / 1000, tz=timezone.utc),
            updated_at=datetime.fromtimestamp(now / 1000, tz=timezone.utc),
            source_path=db_path,
            metadata={"directory": "/workspace/demo", "summary_files": '["a.py","b.py"]'},
        )

        head = agent.get_session_head(session)

        assert head["cwd_or_project"] == "/workspace/demo"
        assert head["model"] == "gpt-4.1"
        assert head["message_count"] == 2
        assert head["subtargets"] == ["a.py", "b.py"]

    def test_export_session_with_tool_parts(self, tmp_path):
        """测试导出包含 tool 类型的 part"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # 创建测试数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

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
        cursor.execute("""
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)

        now = int(datetime.now().timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-001", "Test", now, now, "test", "/test", 1, "file.py"),
        )

        msg_data = json.dumps({"role": "assistant", "agent": "claude"})
        cursor.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("msg-001", "session-001", now, msg_data),
        )

        part_data = json.dumps(
            {
                "type": "tool",
                "tool": "read_file",
                "callID": "call-001",
                "title": "Read File",
                "state": {"path": "/test/file.py"},
            }
        )
        cursor.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            ("part-001", "msg-001", now, part_data),
        )

        conn.commit()
        conn.close()

        agent.db_path = db_path

        session = Session(
            id="session-001",
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=db_path,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        with open(result) as f:
            data = json.load(f)

        assert data["messages"][0]["parts"][0]["type"] == "tool"
        assert data["messages"][0]["parts"][0]["tool"] == "read_file"

    def test_export_session_with_step_parts(self, tmp_path):
        """测试导出包含 step-start/step-finish 类型的 part"""
        agent = OpenCodeAgent()
        db_path = tmp_path / "opencode.db"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

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
        cursor.execute("""
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            )
        """)

        now = int(datetime.now().timestamp() * 1000)
        cursor.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("session-001", "Test", now, now, "test", "/test", 1, "file.py"),
        )

        msg_data = json.dumps({"role": "assistant"})
        cursor.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("msg-001", "session-001", now, msg_data),
        )

        part_data = json.dumps(
            {
                "type": "step-start",
                "reason": "starting_step",
                "tokens": {"input": 10},
                "cost": 0.0001,
            }
        )
        cursor.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            ("part-001", "msg-001", now, part_data),
        )

        conn.commit()
        conn.close()

        agent.db_path = db_path

        session = Session(
            id="session-001",
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=db_path,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        with open(result) as f:
            data = json.load(f)

        assert data["messages"][0]["parts"][0]["type"] == "step-start"
        assert data["messages"][0]["parts"][0]["reason"] == "starting_step"
