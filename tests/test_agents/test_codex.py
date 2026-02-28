"""
测试 agents/codex.py 模块
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.codex import CodexAgent


class TestCodexAgent:
    """测试 CodexAgent 类"""

    def test_init(self):
        """测试初始化"""
        agent = CodexAgent()
        assert agent.name == "codex"
        assert agent.display_name == "Codex"
        assert agent.base_path is None
        assert agent._titles_cache is None

    def test_find_base_path_not_found(self, tmp_path):
        """测试找不到基础路径"""
        agent = CodexAgent()

        with mock.patch.object(Path, "exists", return_value=False):
            result = agent._find_base_path()

        assert result is None

    def test_load_titles_cache_not_exists(self, tmp_path):
        """测试加载不存在的标题缓存"""
        agent = CodexAgent()

        with mock.patch.object(Path, "home", return_value=tmp_path):
            result = agent._load_titles_cache()

        assert result == {}
        assert agent._titles_cache == {}

    def test_load_titles_cache_with_data(self, tmp_path):
        """测试加载有数据的标题缓存"""
        agent = CodexAgent()

        # 创建全局状态文件
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        state_file = codex_dir / ".codex-global-state.json"
        state_data = {
            "thread-titles": {
                "titles": {
                    "session-001": "Test Session",
                    "session-002": "Another Session",
                }
            }
        }
        with open(state_file, "w") as f:
            json.dump(state_data, f)

        with mock.patch.object(Path, "home", return_value=tmp_path):
            result = agent._load_titles_cache()

        assert result == state_data["thread-titles"]["titles"]
        assert agent._titles_cache == state_data["thread-titles"]["titles"]

    def test_load_titles_cache_uses_cache(self, tmp_path):
        """测试标题缓存只加载一次"""
        agent = CodexAgent()
        agent._titles_cache = {"cached": "data"}

        result = agent._load_titles_cache()

        assert result == {"cached": "data"}

    def test_get_session_title_found(self, tmp_path):
        """测试获取存在的会话标题"""
        agent = CodexAgent()
        agent._titles_cache = {"session-001": "Test Title"}

        result = agent._get_session_title("session-001")

        assert result == "Test Title"

    def test_get_session_title_not_found(self, tmp_path):
        """测试获取不存在的会话标题"""
        agent = CodexAgent()
        agent._titles_cache = {"session-001": "Test Title"}

        result = agent._get_session_title("session-999")

        assert result is None

    def test_is_available_no_path(self):
        """测试没有路径时不可用"""
        agent = CodexAgent()

        with mock.patch.object(agent, "_find_base_path", return_value=None):
            result = agent.is_available()

        assert result is False

    def test_is_available_no_jsonl_files(self, tmp_path):
        """测试没有 jsonl 文件时不可用"""
        agent = CodexAgent()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        with mock.patch.object(agent, "_find_base_path", return_value=sessions_dir):
            result = agent.is_available()

        assert result is False

    def test_is_available_with_jsonl_files(self, tmp_path):
        """测试有 jsonl 文件时可用"""
        agent = CodexAgent()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "test.jsonl").touch()

        with mock.patch.object(agent, "_find_base_path", return_value=sessions_dir):
            result = agent.is_available()

        assert result is True

    def test_extract_session_id_from_filename(self):
        """测试从文件名提取会话 ID"""
        agent = CodexAgent()

        file_path = Path("rollout-2026-02-03T10-04-47-019c213e-c251-73a3-af66-0ec9d7cb9e29.jsonl")
        result = agent._extract_session_id_from_filename(file_path)

        assert result == "019c213e-c251-73a3-af66-0ec9d7cb9e29"

    def test_extract_session_id_short_filename(self):
        """测试短文件名提取会话 ID"""
        agent = CodexAgent()

        file_path = Path("short.jsonl")
        result = agent._extract_session_id_from_filename(file_path)

        assert result == "short"

    def test_parse_session_file_empty(self, tmp_path):
        """测试解析空会话文件"""
        agent = CodexAgent()
        file_path = tmp_path / "test.jsonl"
        file_path.write_text("")

        result = agent._parse_session_file(file_path)

        assert result is None

    def test_parse_session_file_valid(self, tmp_path):
        """测试解析有效的会话文件"""
        agent = CodexAgent()
        agent.base_path = tmp_path

        file_path = tmp_path / "rollout-2026-02-03T10-04-47-019c213e-c251-73a3-af66-0ec9d7cb9e29.jsonl"

        timestamp = datetime.now(timezone.utc).isoformat()
        data = {
            "payload": {
                "id": "test-id",
                "timestamp": timestamp,
                "cwd": "/test/dir",
                "cli_version": "1.0.0",
                "model_provider": "openai",
            }
        }
        file_path.write_text(json.dumps(data) + "\n")

        result = agent._parse_session_file(file_path)

        assert result is not None
        assert isinstance(result, Session)
        assert result.metadata["cwd"] == "/test/dir"
        assert result.metadata["cli_version"] == "1.0.0"

    def test_get_sessions_filtered_by_days(self, tmp_path):
        """测试按天数过滤会话"""
        agent = CodexAgent()
        agent.base_path = tmp_path

        # 创建两个会话文件
        new_file = tmp_path / "new.jsonl"
        old_file = tmp_path / "old.jsonl"

        new_timestamp = datetime.now(timezone.utc).isoformat()
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        new_file.write_text(json.dumps({"payload": {"timestamp": new_timestamp}}) + "\n")
        old_file.write_text(json.dumps({"payload": {"timestamp": old_timestamp}}) + "\n")

        result = agent.get_sessions(days=7)

        assert len(result) == 1

    def test_extract_title_from_user_message(self, tmp_path):
        """测试从用户消息提取标题"""
        agent = CodexAgent()

        lines = [
            json.dumps({"payload": {"type": "message", "role": "user", "content": [{"text": "Hello World"}]}}),
            json.dumps({"payload": {"type": "message", "role": "assistant", "content": [{"text": "Hi"}]}}),
        ]

        result = agent._extract_title(lines)

        assert result == "Hello World"

    def test_extract_title_no_user_message(self, tmp_path):
        """测试没有用户消息时使用默认标题"""
        agent = CodexAgent()

        lines = [
            json.dumps({"payload": {"type": "message", "role": "assistant", "content": [{"text": "Hi"}]}}),
        ]

        result = agent._extract_title(lines)

        assert result == "Untitled Session"

    def test_export_session_file_not_found(self, tmp_path):
        """测试导出不存在的会话文件时报错"""
        agent = CodexAgent()

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
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_file = tmp_path / "test.jsonl"
        data = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}],
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        session_file.write_text(json.dumps(data) + "\n")

        session = Session(
            id="test",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_file,
            metadata={"cwd": "/test", "cli_version": "1.0"},
        )

        result = agent.export_session(session, output_dir)

        assert result.exists()
        with open(result) as f:
            exported = json.load(f)

        assert exported["id"] == "test"
        assert exported["title"] == "Test Session"
        assert len(exported["messages"]) == 1

    def test_export_session_filters_developer_and_context_user_messages(self, tmp_path):
        """测试导出时过滤 developer 与注入上下文 user 消息，并保留 tool 部分"""
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_file = tmp_path / "test-filter.jsonl"
        lines = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "System instruction"}],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment_context>\n  <cwd>/tmp</cwd>"}],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "真实用户问题"}],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "read_file",
                    "call_id": "call-001",
                    "arguments": {"path": "/tmp/a.py"},
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="test-filter",
            title="Test Filter Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_file,
            metadata={"cwd": "/test", "cli_version": "1.0"},
        )

        result = agent.export_session(session, output_dir)

        with open(result, encoding="utf-8") as f:
            exported = json.load(f)

        messages = exported["messages"]
        assert all(message["role"] != "developer" for message in messages)
        assert all(
            "<environment_context>" not in part.get("text", "")
            for message in messages
            for part in message.get("parts", [])
        )
        assert any(
            part.get("type") == "tool" and part.get("tool") == "read_file"
            for message in messages
            for part in message.get("parts", [])
        )

    def test_get_session_data_uses_record_timestamps_and_merges_tool_output(self, tmp_path):
        """测试消息时间戳使用原始记录时间，并按 call_id 合并 tool output"""
        agent = CodexAgent()
        session_file = tmp_path / "test-merge.jsonl"
        timestamps = [
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:01Z",
            "2026-01-01T00:00:02Z",
            "2026-01-01T00:00:03Z",
        ]
        lines = [
            {
                "type": "response_item",
                "timestamp": timestamps[0],
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Hello"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": timestamps[1],
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "先执行检查"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": timestamps[2],
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-001",
                    "arguments": {"cmd": "just isok"},
                },
            },
            {
                "type": "response_item",
                "timestamp": timestamps[3],
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-001",
                    "output": "ok",
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="merge",
            title="Merge Session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={"cwd": "/test", "cli_version": "1.0"},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 2
        user_message, assistant_message = result["messages"]
        assert user_message["time_created"] == 1767225600000
        assert user_message["parts"][0]["time_created"] == 1767225600000
        assert assistant_message["time_created"] == 1767225601000
        assert [part["type"] for part in assistant_message["parts"]] == ["text", "tool"]
        assert assistant_message["parts"][0]["time_created"] == 1767225601000
        tool_part = assistant_message["parts"][1]
        assert tool_part["time_created"] == 1767225602000
        assert tool_part["title"] == "bash"
        assert tool_part["state"]["arguments"] == {"cmd": "just isok"}
        assert tool_part["state"]["output"] == [
            {"type": "text", "text": "ok", "time_created": 1767225603000}
        ]

    def test_tool_calls_attach_to_latest_assistant_text_until_next_assistant(self, tmp_path):
        """测试 tool 会归属到最近一条 assistant text，直到下一个 assistant text"""
        agent = CodexAgent()
        session_file = tmp_path / "test-assistant-scope.jsonl"
        lines = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "A"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-001",
                    "arguments": {"cmd": "pwd"},
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:02Z",
                "payload": {
                    "type": "function_call",
                    "name": "spawn_agent",
                    "call_id": "call-002",
                    "arguments": {"task": "x"},
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:03Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "B"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:04Z",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-003",
                    "arguments": {"cmd": "ls"},
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="assistant-scope",
            title="Assistant Scope",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 2
        first_message, second_message = result["messages"]
        first_tool_calls = [part["callID"] for part in first_message["parts"] if part["type"] == "tool"]
        second_tool_calls = [part["callID"] for part in second_message["parts"] if part["type"] == "tool"]
        assert first_tool_calls == ["call-001", "call-002"]
        assert second_tool_calls == ["call-003"]
        assert first_message["parts"][2]["title"] == "spawn_agent"

    def test_function_call_without_assistant_text_creates_fallback_tool_message(self, tmp_path):
        """测试没有前置 assistant text 时，tool call 会退化为 tool-only assistant 消息"""
        agent = CodexAgent()
        session_file = tmp_path / "test-tool-only.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-001",
                        "arguments": {"cmd": "pwd"},
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="tool-only",
            title="Tool Only",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert message["role"] == "assistant"
        assert message["mode"] == "tool"
        assert message["parts"][0]["type"] == "tool"
        assert message["parts"][0]["callID"] == "call-001"

    def test_unmatched_function_call_output_becomes_fallback_tool_message(self, tmp_path):
        """测试无法匹配 call_id 的 output 会退化为 tool 消息"""
        agent = CodexAgent()
        session_file = tmp_path / "test-tool-output.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-999",
                        "output": "orphan output",
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="tool-output",
            title="Tool Output",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert message["role"] == "tool"
        assert message["tool_call_id"] == "call-999"
        assert message["parts"] == [
            {"type": "text", "text": "orphan output", "time_created": 1767225600000}
        ]
