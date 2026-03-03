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
from agent_dump.paths import ProviderRoots

PATCH_INPUT = """*** Begin Patch
*** Add File: /workspace/new.py
+print("new")
*** Update File: /workspace/old.py
@@
-old = 1
+new = 2
 context = True
*** Update File: /workspace/rename.py
*** Move to: /workspace/renamed.py
@@
-before = 1
+after = 2
*** Update File: /workspace/move-only.py
*** Move to: /workspace/moved.py
*** Delete File: /workspace/unused.py
*** End Patch
"""


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
        roots = ProviderRoots(
            codex_root=tmp_path / ".codex",
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / ".kimi",
            opencode_root=tmp_path / ".local" / "share" / "opencode",
        )

        with mock.patch("agent_dump.agents.codex.ProviderRoots.from_env_or_home", return_value=roots):
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

        roots = ProviderRoots(
            codex_root=codex_dir,
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / ".kimi",
            opencode_root=tmp_path / ".local" / "share" / "opencode",
        )

        with mock.patch("agent_dump.agents.codex.ProviderRoots.from_env_or_home", return_value=roots):
            result = agent._load_titles_cache()

        assert result == state_data["thread-titles"]["titles"]
        assert agent._titles_cache == state_data["thread-titles"]["titles"]

    def test_find_base_path_uses_codex_home_env(self, monkeypatch, tmp_path):
        """测试优先使用 CODEX_HOME/sessions"""
        agent = CodexAgent()
        codex_home = tmp_path / "codex-home"
        sessions_dir = codex_home / "sessions"
        sessions_dir.mkdir(parents=True)

        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        result = agent._find_base_path()

        assert result == sessions_dir

    def test_find_base_path_falls_back_to_local_dev(self, monkeypatch, tmp_path):
        """测试回退到本地开发目录 data/codex"""
        agent = CodexAgent()
        monkeypatch.chdir(tmp_path)
        local_dev_path = tmp_path / "data" / "codex"
        local_dev_path.mkdir(parents=True)

        roots = ProviderRoots(
            codex_root=tmp_path / "missing-codex-home",
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / ".kimi",
            opencode_root=tmp_path / ".local" / "share" / "opencode",
        )

        with mock.patch("agent_dump.agents.codex.ProviderRoots.from_env_or_home", return_value=roots):
            result = agent._find_base_path()

        assert result == Path("data/codex")

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

    def test_export_raw_session_copies_original_jsonl(self, tmp_path):
        """测试 raw 导出会复制原始 jsonl 文件"""
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_file = tmp_path / "test.jsonl"
        original = json.dumps({"type": "response_item", "payload": {"type": "message"}}) + "\n"
        session_file.write_text(original, encoding="utf-8")

        session = Session(
            id="test",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_file,
            metadata={},
        )

        result = agent.export_raw_session(session, output_dir)

        assert result.name == "test.raw.jsonl"
        assert result.read_text(encoding="utf-8") == original

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

    def test_assistant_thinking_text_tool_are_grouped_in_order(self, tmp_path):
        """测试 thinking + text + tool 会归并为一条 assistant 消息并保持顺序"""
        agent = CodexAgent()
        session_file = tmp_path / "test-thinking-text-tool.jsonl"
        lines = [
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"type": "agent_reasoning", "text": "thinking"},
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]},
            },
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {"type": "agent_message", "message": "answer"},
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "answer"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:02Z",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-001",
                    "arguments": {"cmd": "pwd"},
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="thinking-text-tool",
            title="Thinking Text Tool",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert [part["type"] for part in message["parts"]] == ["reasoning", "text", "tool"]
        assert message["parts"][0]["text"] == "thinking"
        assert message["parts"][1]["text"] == "answer"
        assert message["parts"][2]["callID"] == "call-001"

    def test_event_reasoning_without_response_item_is_ignored(self, tmp_path):
        """测试只有 event_msg thinking 时不会导出可见 assistant 消息"""
        agent = CodexAgent()
        session_file = tmp_path / "test-thinking-only.jsonl"
        lines = [
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"type": "agent_reasoning", "text": "thinking only"},
            }
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="thinking-only",
            title="Thinking Only",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert result["messages"] == []

    def test_event_text_without_response_item_is_ignored(self, tmp_path):
        """测试只有 event_msg text 时不会导出可见 assistant 消息"""
        agent = CodexAgent()
        session_file = tmp_path / "test-text-only.jsonl"
        lines = [
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"type": "agent_message", "message": "text only"},
            }
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="text-only",
            title="Text Only",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert result["messages"] == []

    def test_tool_does_not_attach_to_event_reasoning_only_message(self, tmp_path):
        """测试 tool 不会挂到仅来自 event_msg 的 thinking 上"""
        agent = CodexAgent()
        session_file = tmp_path / "test-thinking-then-tool.jsonl"
        lines = [
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"type": "agent_reasoning", "text": "thinking only"},
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
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="thinking-then-tool",
            title="Thinking Then Tool",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        tool_message = result["messages"][0]
        assert tool_message["role"] == "assistant"
        assert tool_message["mode"] == "tool"
        assert tool_message["parts"][0]["callID"] == "call-001"

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

    def test_custom_apply_patch_tool_is_structured_and_backfilled(self, tmp_path):
        """测试 apply_patch 会解析为 patch tool，并回填 custom output"""
        agent = CodexAgent()
        session_file = tmp_path / "test-custom-patch.jsonl"
        lines = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "准备修改文件"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "call-patch-001",
                    "status": "completed",
                    "input": PATCH_INPUT,
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:02Z",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call-patch-001",
                    "output": json.dumps(
                        {
                            "output": "Success. Updated the following files:\nA /workspace/new.py\n",
                            "metadata": {"exit_code": 0},
                        }
                    ),
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="custom-patch",
            title="Custom Patch",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert [part["type"] for part in message["parts"]] == ["text", "tool"]

        tool_part = message["parts"][1]
        assert tool_part["tool"] == "patch"
        assert tool_part["title"] == "patch"
        assert tool_part["callID"] == "call-patch-001"

        arguments = tool_part["state"]["arguments"]
        assert arguments["kind"] == "apply_patch"
        assert arguments["raw"] == PATCH_INPUT
        blocks = arguments["content"]
        assert [block["type"] for block in blocks] == [
            "write_file",
            "edit_file",
            "edit_file",
            "move_file",
            "delete_file",
        ]
        assert blocks[0] == {
            "type": "write_file",
            "path": "/workspace/new.py",
            "old_path": None,
            "input": {"content": 'print("new")'},
        }
        assert blocks[1] == {
            "type": "edit_file",
            "path": "/workspace/old.py",
            "old_path": None,
            "input": {
                "content": (
                    "Index: /workspace/old.py\n"
                    "===================================================================\n"
                    "--- /workspace/old.py\n"
                    "+++ /workspace/old.py\n"
                    "@@\n"
                    "-old = 1\n"
                    "+new = 2\n"
                    " context = True"
                )
            },
        }
        assert blocks[2] == {
            "type": "edit_file",
            "path": "/workspace/renamed.py",
            "old_path": "/workspace/rename.py",
            "input": {
                "content": (
                    "Index: /workspace/renamed.py\n"
                    "===================================================================\n"
                    "--- /workspace/rename.py\n"
                    "+++ /workspace/renamed.py\n"
                    "@@\n"
                    "-before = 1\n"
                    "+after = 2"
                )
            },
        }
        assert blocks[3] == {
            "type": "move_file",
            "path": "/workspace/moved.py",
            "old_path": "/workspace/move-only.py",
            "input": {"content": ""},
        }
        assert blocks[4] == {
            "type": "delete_file",
            "path": "/workspace/unused.py",
            "old_path": None,
            "input": {"content": ""},
        }
        assert tool_part["state"]["output"] == [
            {
                "type": "text",
                "text": "Success. Updated the following files:\nA /workspace/new.py\n",
                "time_created": 1767225602000,
            }
        ]

    def test_invalid_apply_patch_keeps_raw_and_parse_error(self, tmp_path):
        """测试无法解析的 apply_patch 仍保留原文并带 parse_error"""
        agent = CodexAgent()
        session_file = tmp_path / "test-invalid-patch.jsonl"
        invalid_patch = "*** Begin Patch\nnot a valid patch\n*** End Patch\n"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "apply_patch",
                        "call_id": "call-patch-invalid",
                        "input": invalid_patch,
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="invalid-patch",
            title="Invalid Patch",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        tool_part = result["messages"][0]["parts"][0]
        arguments = tool_part["state"]["arguments"]
        assert tool_part["tool"] == "patch"
        assert arguments["raw"] == invalid_patch
        assert arguments["content"] == []
        assert "parse_error" in arguments

    def test_unmatched_custom_tool_call_output_becomes_fallback_tool_message(self, tmp_path):
        """测试无法匹配 call_id 的 custom tool output 会退化为 tool 消息"""
        agent = CodexAgent()
        session_file = tmp_path / "test-custom-tool-output.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "call-patch-404",
                        "output": json.dumps({"output": "orphan custom output"}),
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="custom-tool-output",
            title="Custom Tool Output",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert message["role"] == "tool"
        assert message["tool_call_id"] == "call-patch-404"
        assert message["parts"] == [
            {"type": "text", "text": "orphan custom output", "time_created": 1767225600000}
        ]

    def test_plan_part_merges_rejected_user_response(self, tmp_path):
        """测试 plan 会合并后续拒绝 user 响应，并移除该 user 消息"""
        agent = CodexAgent()
        session_file = tmp_path / "test-plan-reject.jsonl"
        lines = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "<proposed_plan>\n# 方案\n\n先改 parser\n</proposed_plan>",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "不行，先别做这个。"}],
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="plan-reject",
            title="Plan Reject",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        plan_part = result["messages"][0]["parts"][0]
        assert plan_part == {
            "type": "plan",
            "input": "# 方案\n\n先改 parser",
            "output": "不行，先别做这个。",
            "approval_status": "fail",
            "time_created": 1767225600000,
        }

    def test_plan_part_marks_success_and_consumes_user_approval(self, tmp_path):
        """测试 plan 批准后 output 为空，审批 user 消息不再导出"""
        agent = CodexAgent()
        session_file = tmp_path / "test-plan-approve.jsonl"
        lines = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "<proposed_plan>\n# 方案\n\n直接实现\n</proposed_plan>",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "PLEASE IMPLEMENT THIS PLAN:\n# 方案\n\n直接实现"}
                    ],
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="plan-approve",
            title="Plan Approve",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        plan_part = result["messages"][0]["parts"][0]
        assert plan_part["type"] == "plan"
        assert plan_part["approval_status"] == "success"
        assert plan_part["output"] is None

    def test_plan_without_following_user_defaults_to_fail(self, tmp_path):
        """测试 plan 后没有 user 时默认 fail"""
        agent = CodexAgent()
        session_file = tmp_path / "test-plan-no-user.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "<proposed_plan>\n只做这一项\n</proposed_plan>"}
                        ],
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="plan-no-user",
            title="Plan No User",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 1
        plan_part = result["messages"][0]["parts"][0]
        assert plan_part["type"] == "plan"
        assert plan_part["approval_status"] == "fail"
        assert plan_part["output"] is None

    def test_multiple_plans_finalize_independently(self, tmp_path):
        """测试多次 plan 会分别结算"""
        agent = CodexAgent()
        session_file = tmp_path / "test-plan-multi.jsonl"
        lines = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "<proposed_plan>\nplan a\n</proposed_plan>"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "<proposed_plan>\nplan b\n</proposed_plan>"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:02Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "PLEASE IMPLEMENT THIS PLAN"}],
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="plan-multi",
            title="Plan Multi",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        plan_parts = [
            part
            for message in result["messages"]
            for part in message["parts"]
            if part.get("type") == "plan"
        ]
        assert len(plan_parts) == 2
        first_plan, second_plan = plan_parts
        assert first_plan["input"] == "plan a"
        assert first_plan["approval_status"] == "fail"
        assert first_plan["output"] is None
        assert second_plan["input"] == "plan b"
        assert second_plan["approval_status"] == "success"
        assert second_plan["output"] is None

    def test_injected_user_context_is_not_used_as_plan_approval(self, tmp_path):
        """测试注入上下文 user 不参与 plan 审批"""
        agent = CodexAgent()
        session_file = tmp_path / "test-plan-context.jsonl"
        lines = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "<proposed_plan>\nplan body\n</proposed_plan>"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment_context>\n  <cwd>/tmp</cwd>"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:02Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "继续后续回复"}],
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="plan-context",
            title="Plan Context",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.get_session_data(session)

        assert len(result["messages"]) == 3
        plan_part = result["messages"][0]["parts"][0]
        assert plan_part["approval_status"] == "fail"
        assert plan_part["output"] is None
        assert result["messages"][1]["role"] == "user"

    def test_export_session_converts_skill_user_message_to_tool_message(self, tmp_path):
        """测试 JSON 导出时 skill user 消息会转换为 assistant tool 消息"""
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        session_file = tmp_path / "test-skill-export.jsonl"
        lines = [
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "普通用户消息"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<skill>\n<name>frontend-design</name>\n</skill>",
                        }
                    ],
                },
            },
        ]
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="skill-export",
            title="Skill Export",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        with open(result, encoding="utf-8") as f:
            exported = json.load(f)

        assert len(exported["messages"]) == 2
        converted = exported["messages"][1]
        assert converted["role"] == "assistant"
        assert converted["mode"] == "tool"
        assert converted["parts"][0]["tool"] == "skill"
        assert converted["parts"][0]["title"] == "skill"
        assert converted["parts"][0]["state"]["status"] == "completed"
        assert converted["parts"][0]["state"]["input"] == {"name": "frontend-design"}
        assert converted["parts"][0]["state"]["output"] is None

    def test_export_session_assigns_stable_skill_call_ids(self, tmp_path):
        """测试多条 skill 消息在 JSON 导出中按顺序生成稳定 callID"""
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        session_file = tmp_path / "test-skill-call-id.jsonl"
        skill_names = ["frontend-design", "ui-ux-pro-max", "web-design-guidelines"]
        lines = []
        for index, skill_name in enumerate(skill_names):
            lines.append(
                {
                    "type": "response_item",
                    "timestamp": f"2026-01-01T00:00:0{index}Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f"<skill>\n<name>{skill_name}</name>\n</skill>",
                            }
                        ],
                    },
                }
            )
        session_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        session = Session(
            id="skill-call-id",
            title="Skill Call Id",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        with open(result, encoding="utf-8") as f:
            exported = json.load(f)

        call_ids = [message["parts"][0]["callID"] for message in exported["messages"]]
        assert call_ids == ["skill:0", "skill:1", "skill:2"]

    def test_export_session_keeps_skill_message_without_name_as_user_text(self, tmp_path):
        """测试缺少 name 的 skill 文本保持原始 user 消息"""
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        session_file = tmp_path / "test-skill-missing-name.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "<skill>\n<path>/tmp/x</path>\n</skill>"}],
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="skill-missing-name",
            title="Skill Missing Name",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        with open(result, encoding="utf-8") as f:
            exported = json.load(f)

        message = exported["messages"][0]
        assert message["role"] == "user"
        assert message["parts"] == [
            {"type": "text", "text": "<skill>\n<path>/tmp/x</path>\n</skill>", "time_created": 1767225600000}
        ]

    def test_export_session_keeps_normal_user_text_unchanged(self, tmp_path):
        """测试普通 user 文本导出行为不变"""
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        session_file = tmp_path / "test-normal-user.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello world"}],
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="normal-user",
            title="Normal User",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        result = agent.export_session(session, output_dir)

        with open(result, encoding="utf-8") as f:
            exported = json.load(f)

        assert exported["messages"] == [
            {
                "id": "2026-01-01T00:00:00Z",
                "role": "user",
                "agent": None,
                "mode": None,
                "model": None,
                "provider": None,
                "time_created": 1767225600000,
                "time_completed": None,
                "tokens": {},
                "cost": 0,
                "parts": [{"type": "text", "text": "hello world", "time_created": 1767225600000}],
            }
        ]

    def test_skill_message_transforms_only_in_json_export(self, tmp_path):
        """测试 skill 消息仅在 JSON 导出时转换，get_session_data 保持原样"""
        agent = CodexAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        session_file = tmp_path / "test-skill-json-only.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "<skill>\n<name>frontend-design</name>\n</skill>"}],
                    },
                }
            )
            + "\n"
        )

        session = Session(
            id="skill-json-only",
            title="Skill Json Only",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_file,
            metadata={},
        )

        session_data = agent.get_session_data(session)
        assert session_data["messages"][0]["role"] == "user"
        assert session_data["messages"][0]["parts"] == [
            {
                "type": "text",
                "text": "<skill>\n<name>frontend-design</name>\n</skill>",
                "time_created": 1767225600000,
            }
        ]

        result = agent.export_session(session, output_dir)

        with open(result, encoding="utf-8") as f:
            exported = json.load(f)

        converted = exported["messages"][0]
        assert converted["role"] == "assistant"
        assert converted["mode"] == "tool"
        assert converted["parts"][0]["tool"] == "skill"
