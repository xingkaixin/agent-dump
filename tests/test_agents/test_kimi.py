"""
测试 agents/kimi.py 模块
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.kimi import KimiAgent


class TestKimiAgent:
    """测试 KimiAgent 类"""

    def test_init(self):
        """测试初始化"""
        agent = KimiAgent()
        assert agent.name == "kimi"
        assert agent.display_name == "Kimi"
        assert agent.base_path is None

    def test_find_base_path_not_found(self):
        """测试找不到基础路径"""
        agent = KimiAgent()

        with mock.patch.object(Path, "exists", return_value=False):
            result = agent._find_base_path()

        assert result is None

    def test_is_available_no_path(self):
        """测试没有路径时不可用"""
        agent = KimiAgent()

        with mock.patch.object(agent, "_find_base_path", return_value=None):
            result = agent.is_available()

        assert result is False

    def test_is_available_no_metadata(self, tmp_path):
        """测试没有 metadata.json 时不可用"""
        agent = KimiAgent()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        with mock.patch.object(agent, "_find_base_path", return_value=sessions_dir):
            result = agent.is_available()

        assert result is False

    def test_is_available_with_metadata(self, tmp_path):
        """测试有 metadata.json 时可用"""
        agent = KimiAgent()
        sessions_dir = tmp_path / "sessions"
        project_dir = sessions_dir / "project1"
        session_dir = project_dir / "session1"
        session_dir.mkdir(parents=True)
        (session_dir / "metadata.json").touch()

        with mock.patch.object(agent, "_find_base_path", return_value=sessions_dir):
            result = agent.is_available()

        assert result is True

    def test_parse_session_valid(self, tmp_path):
        """测试解析有效的会话"""
        agent = KimiAgent()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        metadata = {
            "session_id": "test-session-001",
            "title": "Test Session",
            "wire_mtime": datetime.now().timestamp(),
            "title_generated": True,
        }
        metadata_file = session_dir / "metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata, f)

        # 创建 wire.jsonl 文件
        (session_dir / "wire.jsonl").touch()

        result = agent._parse_session(metadata_file)

        assert result is not None
        assert isinstance(result, Session)
        assert result.id == "test-session-001"
        assert result.title == "Test Session"
        assert result.metadata["title_generated"] is True

    def test_parse_session_no_wire_file(self, tmp_path):
        """测试没有 wire.jsonl 时返回 None"""
        agent = KimiAgent()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        metadata = {"session_id": "test", "title": "Test"}
        metadata_file = session_dir / "metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata, f)

        result = agent._parse_session(metadata_file)

        assert result is None

    def test_parse_session_invalid_json(self, tmp_path):
        """测试无效的 JSON 返回 None"""
        agent = KimiAgent()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        metadata_file = session_dir / "metadata.json"
        metadata_file.write_text("invalid json")
        (session_dir / "wire.jsonl").touch()

        result = agent._parse_session(metadata_file)

        assert result is None

    def test_get_sessions_filtered_by_days(self, tmp_path):
        """测试按天数过滤会话"""
        agent = KimiAgent()
        agent.base_path = tmp_path

        # 创建两个会话
        old_session_dir = tmp_path / "old"
        new_session_dir = tmp_path / "new"
        old_session_dir.mkdir()
        new_session_dir.mkdir()

        # 旧会话
        old_metadata = {
            "session_id": "old-session",
            "title": "Old",
            "wire_mtime": (datetime.now() - timedelta(days=10)).timestamp(),
        }
        with open(old_session_dir / "metadata.json", "w") as f:
            json.dump(old_metadata, f)
        (old_session_dir / "wire.jsonl").touch()

        # 新会话
        new_metadata = {
            "session_id": "new-session",
            "title": "New",
            "wire_mtime": datetime.now().timestamp(),
        }
        with open(new_session_dir / "metadata.json", "w") as f:
            json.dump(new_metadata, f)
        (new_session_dir / "wire.jsonl").touch()

        result = agent.get_sessions(days=7)

        assert len(result) == 1
        assert result[0].id == "new-session"

    def test_get_sessions_sorted_by_time(self, tmp_path):
        """测试会话按时间倒序排列"""
        agent = KimiAgent()
        agent.base_path = tmp_path

        # 创建两个会话
        session1_dir = tmp_path / "session1"
        session2_dir = tmp_path / "session2"
        session1_dir.mkdir()
        session2_dir.mkdir()

        now = datetime.now()
        yesterday = now - timedelta(days=1)

        metadata1 = {
            "session_id": "session-001",
            "title": "Yesterday",
            "wire_mtime": yesterday.timestamp(),
        }
        with open(session1_dir / "metadata.json", "w") as f:
            json.dump(metadata1, f)
        (session1_dir / "wire.jsonl").touch()

        metadata2 = {
            "session_id": "session-002",
            "title": "Today",
            "wire_mtime": now.timestamp(),
        }
        with open(session2_dir / "metadata.json", "w") as f:
            json.dump(metadata2, f)
        (session2_dir / "wire.jsonl").touch()

        result = agent.get_sessions(days=7)

        assert len(result) == 2
        assert result[0].id == "session-002"
        assert result[1].id == "session-001"

    def test_export_session_wire_not_found(self, tmp_path):
        """测试 wire.jsonl 不存在时报错"""
        agent = KimiAgent()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        session = Session(
            id="test",
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_dir,
            metadata={},
        )

        with pytest.raises(FileNotFoundError):
            agent.export_session(session, tmp_path)

    def test_export_session_valid(self, tmp_path):
        """测试导出有效的会话"""
        agent = KimiAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        # 创建 wire.jsonl
        wire_file = session_dir / "wire.jsonl"
        wire_data = {
            "timestamp": datetime.now().timestamp(),
            "message": {
                "type": "TurnBegin",
                "payload": {
                    "user_input": [{"text": "Hello Kimi"}],
                },
            },
        }
        with open(wire_file, "w") as f:
            f.write(json.dumps(wire_data) + "\n")

        session = Session(
            id="test-session",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_dir,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        assert result.exists()
        with open(result) as f:
            exported = json.load(f)

        assert exported["id"] == "test-session"
        assert exported["title"] == "Test Session"
        assert len(exported["messages"]) == 1

    def test_convert_to_opencode_format_turn_begin(self):
        """测试 TurnBegin 类型转换"""
        agent = KimiAgent()

        timestamp = datetime.now().timestamp()
        data = {
            "timestamp": timestamp,
            "message": {
                "type": "TurnBegin",
                "payload": {
                    "user_input": [{"text": "Hello"}],
                },
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["role"] == "user"
        assert result["parts"][0]["text"] == "Hello"

    def test_convert_to_opencode_format_content_part_text(self):
        """测试 ContentPart text 类型转换"""
        agent = KimiAgent()

        timestamp = datetime.now().timestamp()
        data = {
            "timestamp": timestamp,
            "message": {
                "type": "ContentPart",
                "payload": {
                    "type": "text",
                    "text": "Response text",
                },
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["role"] == "assistant"
        assert result["agent"] == "kimi"
        assert result["parts"][0]["type"] == "text"
        assert result["parts"][0]["text"] == "Response text"

    def test_convert_to_opencode_format_content_part_think(self):
        """测试 ContentPart think 类型转换"""
        agent = KimiAgent()

        timestamp = datetime.now().timestamp()
        data = {
            "timestamp": timestamp,
            "message": {
                "type": "ContentPart",
                "payload": {
                    "type": "think",
                    "think": "Thinking process",
                },
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["parts"][0]["type"] == "reasoning"
        assert result["parts"][0]["text"] == "Thinking process"

    def test_convert_to_opencode_format_tool_call(self):
        """测试 ToolCall 类型转换"""
        agent = KimiAgent()

        timestamp = datetime.now().timestamp()
        data = {
            "timestamp": timestamp,
            "message": {
                "type": "ToolCall",
                "payload": {
                    "function": {
                        "name": "read_file",
                        "id": "call-001",
                        "arguments": {"path": "/test/file.py"},
                    },
                },
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["role"] == "assistant"
        assert result["mode"] == "tool"
        assert result["parts"][0]["type"] == "tool"
        assert result["parts"][0]["tool"] == "read_file"

    def test_convert_to_opencode_format_tool_result(self):
        """测试 ToolResult 类型转换"""
        agent = KimiAgent()

        timestamp = datetime.now().timestamp()
        data = {
            "timestamp": timestamp,
            "message": {
                "type": "ToolResult",
                "payload": {
                    "return_value": {"content": "file content"},
                },
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["role"] == "tool"
        assert result["parts"][0]["type"] == "text"
        assert "file content" in result["parts"][0]["text"]

    def test_convert_to_opencode_format_unknown_type(self):
        """测试未知类型返回 None"""
        agent = KimiAgent()

        data = {
            "timestamp": datetime.now().timestamp(),
            "message": {
                "type": "UnknownType",
                "payload": {},
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is None

    def test_convert_to_opencode_format_content_part_other(self):
        """测试 ContentPart 其他类型返回 None"""
        agent = KimiAgent()

        timestamp = datetime.now().timestamp()
        data = {
            "timestamp": timestamp,
            "message": {
                "type": "ContentPart",
                "payload": {
                    "type": "unknown",
                },
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is None

    def test_export_session_extracts_tokens(self, tmp_path):
        """测试导出时提取 token 使用情况"""
        agent = KimiAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        # 创建包含 token 使用数据的 wire.jsonl
        wire_file = session_dir / "wire.jsonl"
        wire_data = {
            "timestamp": datetime.now().timestamp(),
            "message": {
                "type": "TurnBegin",
                "payload": {"user_input": [{"text": "Hello"}]},
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        }
        with open(wire_file, "w") as f:
            f.write(json.dumps(wire_data) + "\n")

        session = Session(
            id="test",
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_dir,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        with open(result) as f:
            exported = json.load(f)

        assert exported["stats"]["total_input_tokens"] == 10
        assert exported["stats"]["total_output_tokens"] == 20
