"""
测试 agents/claudecode.py 模块
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.claudecode import ClaudeCodeAgent


class TestClaudeCodeAgent:
    """测试 ClaudeCodeAgent 类"""

    def test_init(self):
        """测试初始化"""
        agent = ClaudeCodeAgent()
        assert agent.name == "claudecode"
        assert agent.display_name == "Claude Code"
        assert agent.base_path is None
        assert agent._sessions_index_cache == {}

    def test_find_base_path_not_found(self):
        """测试找不到基础路径"""
        agent = ClaudeCodeAgent()

        with mock.patch.object(Path, "exists", return_value=False):
            result = agent._find_base_path()

        assert result is None

    def test_load_sessions_index_not_exists(self, tmp_path):
        """测试加载不存在的 sessions index"""
        agent = ClaudeCodeAgent()
        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        result = agent._load_sessions_index(project_dir)

        assert result == {}

    def test_load_sessions_index_with_data(self, tmp_path):
        """测试加载有数据的 sessions index"""
        agent = ClaudeCodeAgent()
        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        index_data = {
            "entries": [
                {"sessionId": "session-001", "summary": "Test Session"},
                {"sessionId": "session-002", "summary": "Another Session"},
            ]
        }
        index_file = project_dir / "sessions-index.json"
        with open(index_file, "w") as f:
            json.dump(index_data, f)

        result = agent._load_sessions_index(project_dir)

        assert result == {
            "session-001": {"sessionId": "session-001", "summary": "Test Session"},
            "session-002": {"sessionId": "session-002", "summary": "Another Session"},
        }

    def test_get_session_metadata_from_cache(self, tmp_path):
        """测试从缓存获取会话元数据"""
        agent = ClaudeCodeAgent()
        cache_key = "project1:session-001"
        agent._sessions_index_cache[cache_key] = {"summary": "Cached Session"}

        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        result = agent._get_session_metadata("session-001", project_dir)

        assert result == {"summary": "Cached Session"}

    def test_get_session_metadata_loads_index(self, tmp_path):
        """测试加载 index 文件获取元数据"""
        agent = ClaudeCodeAgent()
        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        index_data = {
            "entries": [
                {"sessionId": "session-001", "summary": "Test Session"},
            ]
        }
        with open(project_dir / "sessions-index.json", "w") as f:
            json.dump(index_data, f)

        result = agent._get_session_metadata("session-001", project_dir)

        assert result == {"sessionId": "session-001", "summary": "Test Session"}

    def test_is_available_no_path(self):
        """测试没有路径时不可用"""
        agent = ClaudeCodeAgent()

        with mock.patch.object(agent, "_find_base_path", return_value=None):
            result = agent.is_available()

        assert result is False

    def test_is_available_no_jsonl_files(self, tmp_path):
        """测试没有 jsonl 文件时不可用"""
        agent = ClaudeCodeAgent()
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "project1"
        project_dir.mkdir(parents=True)

        with mock.patch.object(agent, "_find_base_path", return_value=projects_dir):
            result = agent.is_available()

        assert result is False

    def test_is_available_with_jsonl_files(self, tmp_path):
        """测试有 jsonl 文件时可用"""
        agent = ClaudeCodeAgent()
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "project1"
        project_dir.mkdir(parents=True)
        (project_dir / "session.jsonl").touch()

        with mock.patch.object(agent, "_find_base_path", return_value=projects_dir):
            result = agent.is_available()

        assert result is True

    def test_parse_session_file_empty(self, tmp_path):
        """测试解析空会话文件"""
        agent = ClaudeCodeAgent()
        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        file_path = project_dir / "session.jsonl"
        file_path.write_text("")

        result = agent._parse_session_file(file_path, project_dir)

        assert result is None

    def test_parse_session_file_valid(self, tmp_path):
        """测试解析有效的会话文件"""
        agent = ClaudeCodeAgent()
        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        file_path = project_dir / "session-001.jsonl"
        timestamp = datetime.now(UTC).isoformat()
        data = {
            "timestamp": timestamp,
            "cwd": "/test/dir",
            "version": "1.0.0",
        }
        file_path.write_text(json.dumps(data) + "\n")

        result = agent._parse_session_file(file_path, project_dir)

        assert result is not None
        assert isinstance(result, Session)
        assert result.id == "session-001"
        assert result.metadata["project"] == "project1"
        assert result.metadata["cwd"] == "/test/dir"

    def test_parse_session_file_with_index_title(self, tmp_path):
        """测试从 index 文件获取标题"""
        agent = ClaudeCodeAgent()
        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        # 创建 index 文件
        index_data = {
            "entries": [
                {"sessionId": "session-001", "summary": "Index Title"},
            ]
        }
        with open(project_dir / "sessions-index.json", "w") as f:
            json.dump(index_data, f)

        file_path = project_dir / "session-001.jsonl"
        file_path.write_text(json.dumps({"timestamp": datetime.now(UTC).isoformat()}) + "\n")

        result = agent._parse_session_file(file_path, project_dir)

        assert result is not None
        assert result.title == "Index Title"

    def test_get_sessions_filtered_by_days(self, tmp_path):
        """测试按天数过滤会话"""
        agent = ClaudeCodeAgent()
        agent.base_path = tmp_path

        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        # 创建两个会话文件
        new_file = project_dir / "new.jsonl"
        old_file = project_dir / "old.jsonl"

        new_timestamp = datetime.now(UTC).isoformat()
        old_timestamp = (datetime.now(UTC) - timedelta(days=10)).isoformat()

        new_file.write_text(json.dumps({"timestamp": new_timestamp}) + "\n")
        old_file.write_text(json.dumps({"timestamp": old_timestamp}) + "\n")

        result = agent.get_sessions(days=7)

        assert len(result) == 1

    def test_get_sessions_skips_index_file(self, tmp_path):
        """测试跳过 index 文件"""
        agent = ClaudeCodeAgent()
        agent.base_path = tmp_path

        project_dir = tmp_path / "project1"
        project_dir.mkdir()

        # 创建 index 文件和普通会话文件
        index_file = project_dir / "sessions-index.json"
        session_file = project_dir / "session.jsonl"

        index_file.write_text("{}")
        session_file.write_text(json.dumps({"timestamp": datetime.now(UTC).isoformat()}) + "\n")

        result = agent.get_sessions(days=7)

        assert len(result) == 1

    def test_extract_title_from_user_message(self):
        """测试从用户消息提取标题"""
        agent = ClaudeCodeAgent()

        lines = [
            json.dumps({"message": {"role": "user", "content": "Hello World"}}),
            json.dumps({"message": {"role": "assistant", "content": "Hi"}}),
        ]

        result = agent._extract_title(lines)

        assert result == "Hello World"

    def test_extract_title_from_list_content(self):
        """测试从列表类型的 content 提取标题"""
        agent = ClaudeCodeAgent()

        lines = [
            json.dumps({"message": {"role": "user", "content": [{"text": "List content"}]}}),
        ]

        result = agent._extract_title(lines)

        assert result == "List content"

    def test_extract_title_no_user_message(self):
        """测试没有用户消息时使用默认标题"""
        agent = ClaudeCodeAgent()

        lines = [
            json.dumps({"message": {"role": "assistant", "content": "Hi"}}),
        ]

        result = agent._extract_title(lines)

        assert result == "Untitled Session"

    def test_export_session_file_not_found(self, tmp_path):
        """测试导出不存在的会话文件时报错"""
        agent = ClaudeCodeAgent()

        session = Session(
            id="test",
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=tmp_path / "nonexistent.jsonl",
            metadata={},
        )

        with pytest.raises(FileNotFoundError):
            agent.export_session(session, tmp_path)

    def test_export_session_valid(self, tmp_path):
        """测试导出有效的会话"""
        agent = ClaudeCodeAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_file = tmp_path / "test.jsonl"
        data = {
            "type": "user",
            "uuid": "msg-001",
            "timestamp": datetime.now(UTC).isoformat(),
            "message": {
                "role": "user",
                "content": "Hello Claude",
            },
        }
        session_file.write_text(json.dumps(data) + "\n")

        session = Session(
            id="test",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_file,
            metadata={"cwd": "/test", "version": "1.0"},
        )

        result = agent.export_session(session, output_dir)

        assert result.exists()
        with open(result) as f:
            exported = json.load(f)

        assert exported["id"] == "test"
        assert exported["title"] == "Test Session"
        assert len(exported["messages"]) == 1

    def test_convert_to_opencode_format_user(self):
        """测试 user 类型消息转换"""
        agent = ClaudeCodeAgent()

        data = {
            "type": "user",
            "uuid": "msg-001",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "user",
                "content": "Hello",
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["role"] == "user"
        assert result["id"] == "msg-001"
        assert result["parts"][0]["text"] == "Hello"

    def test_convert_to_opencode_format_assistant_text(self):
        """测试 assistant text 类型消息转换"""
        agent = ClaudeCodeAgent()

        data = {
            "type": "assistant",
            "uuid": "msg-002",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "model": "claude-3-opus",
                "content": [{"type": "text", "text": "Response"}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["role"] == "assistant"
        assert result["agent"] == "claude"
        assert result["model"] == "claude-3-opus"
        assert result["tokens"] == {"input_tokens": 10, "output_tokens": 20}
        assert result["parts"][0]["type"] == "text"

    def test_convert_to_opencode_format_assistant_tool_use(self):
        """测试 assistant tool_use 类型消息转换"""
        agent = ClaudeCodeAgent()

        data = {
            "type": "assistant",
            "uuid": "msg-003",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "read_file",
                        "id": "tool-001",
                        "input": {"path": "/test/file.py"},
                    }
                ],
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["parts"][0]["type"] == "tool"
        assert result["parts"][0]["tool"] == "read_file"
        assert result["parts"][0]["state"]["input"]["path"] == "/test/file.py"

    def test_convert_to_opencode_format_tool_result(self):
        """测试 tool_result 类型消息转换"""
        agent = ClaudeCodeAgent()

        data = {
            "type": "tool_result",
            "uuid": "msg-004",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "tool",
                "content": [{"text": "Tool output"}],
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["role"] == "tool"
        assert result["parts"][0]["text"] == "Tool output"

    def test_convert_to_opencode_format_tool_result_string_content(self):
        """测试 tool_result 字符串 content 类型消息转换"""
        agent = ClaudeCodeAgent()

        data = {
            "type": "tool_result",
            "uuid": "msg-005",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "tool",
                "content": "String content",
            },
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["parts"][0]["text"] == "String content"

    def test_convert_to_opencode_format_unknown_type(self):
        """测试未知类型返回 None"""
        agent = ClaudeCodeAgent()

        data = {"type": "unknown", "timestamp": "2026-01-01T00:00:00Z", "message": {}}
        result = agent._convert_to_opencode_format(data)

        assert result is None

    def test_convert_to_opencode_format_invalid_timestamp(self):
        """测试无效时间戳处理"""
        agent = ClaudeCodeAgent()

        data = {
            "type": "user",
            "uuid": "msg-001",
            "timestamp": "invalid-timestamp",
            "message": {"content": "Hello"},
        }
        result = agent._convert_to_opencode_format(data)

        assert result is not None
        assert result["time_created"] == 0
