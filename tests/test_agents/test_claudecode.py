"""
测试 agents/claudecode.py 模块
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.claudecode import ClaudeCodeAgent


def write_jsonl(file_path: Path, records: list[dict]) -> None:
    """写入 jsonl 文件。"""
    file_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def make_session(file_path: Path) -> Session:
    """构造测试 session。"""
    now = datetime.now(timezone.utc)
    return Session(
        id=file_path.stem,
        title="Test Session",
        created_at=now,
        updated_at=now,
        source_path=file_path,
        metadata={"cwd": "/test", "version": "1.0"},
    )


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
        timestamp = datetime.now(timezone.utc).isoformat()
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
        file_path.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")

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

        new_timestamp = datetime.now(timezone.utc).isoformat()
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

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
        session_file.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")

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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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

    def test_export_raw_session_copies_original_jsonl(self, tmp_path):
        """测试 raw 导出会复制原始 jsonl 文件"""
        agent = ClaudeCodeAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_file = tmp_path / "test.jsonl"
        original = json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}) + "\n"
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

    def test_get_session_data_drops_todowrite_tool_and_result(self, tmp_path):
        """测试 TodoWrite tool_use 和 tool_result 都会被移除。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "todo-only.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "TodoWrite",
                                "id": "call-todo",
                                "input": {"todos": []},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-todo",
                                "content": "Todos updated",
                            }
                        ],
                    },
                },
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert result["messages"] == []

    def test_get_session_data_keeps_assistant_text_when_todowrite_is_filtered(self, tmp_path):
        """测试 assistant 文本和 TodoWrite 混合时文本仍保留。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "todo-with-text.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "先分析一下"},
                            {
                                "type": "tool_use",
                                "name": "TodoWrite",
                                "id": "call-todo",
                                "input": {"todos": []},
                            },
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-todo",
                                "content": "Todos updated",
                            }
                        ],
                    },
                },
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "assistant"
        assert result["messages"][0]["parts"] == [
            {"type": "text", "text": "先分析一下", "time_created": 1767225600000}
        ]

    def test_get_session_data_backfills_regular_tool_output(self, tmp_path):
        """测试普通工具输出会回填到 assistant tool part。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "tool-merge.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-3-opus",
                        "usage": {"input_tokens": 10, "output_tokens": 20},
                        "content": [
                            {"type": "text", "text": "读取文件"},
                            {
                                "type": "tool_use",
                                "name": "read_file",
                                "id": "call-001",
                                "input": {"path": "src/main.py"},
                            },
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-001",
                                "content": "file content",
                            }
                        ],
                    },
                },
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 1
        assistant = result["messages"][0]
        assert assistant["role"] == "assistant"
        assert assistant["model"] == "claude-3-opus"
        assert assistant["tokens"] == {"input_tokens": 10, "output_tokens": 20}
        assert [part["type"] for part in assistant["parts"]] == ["text", "tool"]
        assert assistant["parts"][1]["state"]["input"] == {"path": "src/main.py"}
        assert assistant["parts"][1]["state"]["output"] == [
            {"type": "text", "text": "file content", "time_created": 1767225601000}
        ]
        assert assistant["parts"][1]["state"]["status"] == "completed"

    def test_get_session_data_groups_thinking_only_as_single_message(self, tmp_path):
        """测试只有 thinking 时保持单独 assistant 消息。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "thinking-only.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "thinking", "thinking": "先想一下"}],
                    },
                }
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 1
        assert result["messages"][0]["parts"] == [
            {"type": "reasoning", "text": "先想一下", "time_created": 1767225600000}
        ]

    def test_get_session_data_groups_thinking_text_tool_in_order(self, tmp_path):
        """测试 thinking + text + tool 会归并为一条 assistant 消息并保持顺序。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "thinking-text-tool.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-thinking",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "thinking", "thinking": "thinking"}],
                    },
                },
                {
                    "type": "assistant",
                    "uuid": "assistant-text",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "answer"}],
                    },
                },
                {
                    "type": "assistant",
                    "uuid": "assistant-tool",
                    "timestamp": "2026-01-01T00:00:02Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "read_file",
                                "id": "call-001",
                                "input": {"path": "src/main.py"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:03Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-001",
                                "content": "file content",
                            }
                        ],
                    },
                },
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert [part["type"] for part in message["parts"]] == ["reasoning", "text", "tool"]
        assert message["parts"][0]["text"] == "thinking"
        assert message["parts"][1]["text"] == "answer"
        assert message["parts"][2]["callID"] == "call-001"
        assert message["parts"][2]["state"]["output"] == [
            {"type": "text", "text": "file content", "time_created": 1767225603000}
        ]

    def test_get_session_data_groups_text_and_tool_in_order(self, tmp_path):
        """测试 text + tool 会归并为一条 assistant 消息并保持顺序。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "text-tool.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-text",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "我来读取文件"}],
                    },
                },
                {
                    "type": "assistant",
                    "uuid": "assistant-tool",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "read_file",
                                "id": "call-001",
                                "input": {"path": "src/main.py"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:02Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-001",
                                "content": "file content",
                            }
                        ],
                    },
                },
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert [part["type"] for part in message["parts"]] == ["text", "tool"]
        assert message["parts"][0]["text"] == "我来读取文件"
        assert message["parts"][1]["callID"] == "call-001"
        assert message["parts"][1]["state"]["output"] == [
            {"type": "text", "text": "file content", "time_created": 1767225602000}
        ]

    def test_get_session_data_backfills_skill_and_filters_meta(self, tmp_path):
        """测试 Skill 工具结果回填，isMeta 注入消息被过滤。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "skill.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Skill",
                                "id": "call-skill",
                                "input": {"skill": "mcp-chinabigdata"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-skill",
                                "content": "Launching skill: mcp-chinabigdata",
                            }
                        ],
                    },
                    "toolUseResult": {"success": True, "commandName": "mcp-chinabigdata"},
                    "sourceToolAssistantUUID": "assistant-1",
                },
                {
                    "type": "user",
                    "uuid": "user-meta",
                    "timestamp": "2026-01-01T00:00:02Z",
                    "isMeta": True,
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Base directory for this skill: ..."}],
                    },
                },
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 1
        assistant = result["messages"][0]
        assert assistant["mode"] == "tool"
        assert assistant["parts"][0]["tool"] == "Skill"
        assert assistant["parts"][0]["state"]["output"] == [
            {
                "type": "text",
                "text": "Launching skill: mcp-chinabigdata",
                "time_created": 1767225601000,
            }
        ]
        assert assistant["parts"][0]["state"]["status"] == "success"
        assert assistant["parts"][0]["state"]["meta"] == {"commandName": "mcp-chinabigdata"}
        assert "Base directory for this skill" not in json.dumps(result, ensure_ascii=False)

    def test_get_session_data_keeps_user_text_when_tool_result_is_removed(self, tmp_path):
        """测试 user 消息混合文本与 tool_result 时仅移除 tool_result。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "mixed-user.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "assistant",
                    "uuid": "assistant-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "read_file",
                                "id": "call-001",
                                "input": {"path": "src/main.py"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请继续"},
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-001",
                                "content": "file content",
                            },
                        ],
                    },
                },
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 2
        assert result["messages"][1]["role"] == "user"
        assert result["messages"][1]["parts"] == [
            {"type": "text", "text": "请继续", "time_created": 1767225601000}
        ]
        assert result["messages"][0]["parts"][0]["state"]["output"] == [
            {"type": "text", "text": "file content", "time_created": 1767225601000}
        ]

    def test_get_session_data_unmatched_tool_result_becomes_fallback_tool_message(self, tmp_path):
        """测试无法匹配的 tool_result 会退化为独立 tool 消息。"""
        agent = ClaudeCodeAgent()
        session_file = tmp_path / "fallback-tool.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "user",
                    "uuid": "user-1",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-missing",
                                "content": "orphan output",
                            }
                        ],
                    },
                }
            ],
        )

        result = agent.get_session_data(make_session(session_file))

        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "tool"
        assert result["messages"][0]["tool_call_id"] == "call-missing"
        assert result["messages"][0]["parts"] == [
            {"type": "text", "text": "orphan output", "time_created": 1767225601000}
        ]

    def test_export_session_filters_claude_tool_noise_on_realistic_flow(self, tmp_path):
        """测试完整导出链路会清洗 TodoWrite、Skill meta，并回填正常工具输出。"""
        agent = ClaudeCodeAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        session_file = tmp_path / "realistic.jsonl"
        write_jsonl(
            session_file,
            [
                {
                    "type": "user",
                    "uuid": "u-1",
                    "timestamp": "2026-02-12T08:27:00Z",
                    "message": {"role": "user", "content": "招商证券最新行情"},
                },
                {
                    "type": "assistant",
                    "uuid": "a-1",
                    "timestamp": "2026-02-12T08:27:04Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "我来帮您查询。"}],
                    },
                },
                {
                    "type": "assistant",
                    "uuid": "a-todo",
                    "timestamp": "2026-02-12T08:27:04Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "TodoWrite",
                                "id": "call-todo",
                                "input": {"todos": []},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "u-todo",
                    "timestamp": "2026-02-12T08:27:04Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-todo",
                                "content": "Todos updated",
                            }
                        ],
                    },
                },
                {
                    "type": "assistant",
                    "uuid": "a-skill",
                    "timestamp": "2026-02-12T08:27:07Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Skill",
                                "id": "call-skill",
                                "input": {"skill": "mcp-chinabigdata"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "u-skill",
                    "timestamp": "2026-02-12T08:27:07Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-skill",
                                "content": "Launching skill: mcp-chinabigdata",
                            }
                        ],
                    },
                    "toolUseResult": {"success": True, "commandName": "mcp-chinabigdata"},
                    "sourceToolAssistantUUID": "a-skill",
                },
                {
                    "type": "user",
                    "uuid": "u-meta",
                    "timestamp": "2026-02-12T08:27:07Z",
                    "isMeta": True,
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Base directory for this skill: ..."}],
                    },
                },
                {
                    "type": "assistant",
                    "uuid": "a-get",
                    "timestamp": "2026-02-12T08:27:10Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "mcp__chinabigdata__getIndexSubject",
                                "id": "call-get",
                                "input": {"content": "招商证券最新行情", "individualName": "招商证券"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "u-get",
                    "timestamp": "2026-02-12T08:27:11Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-get",
                                "content": "{\"iid\":\"600999.SH\"}",
                            }
                        ],
                    },
                    "sourceToolAssistantUUID": "a-get",
                },
                {
                    "type": "assistant",
                    "uuid": "a-quote",
                    "timestamp": "2026-02-12T08:27:14Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "mcp__chinabigdata__realtimeQuote",
                                "id": "call-quote",
                                "input": {"individualName": "600999.SH"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "uuid": "u-quote",
                    "timestamp": "2026-02-12T08:27:15Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-quote",
                                "content": "[{\"最新价\":\"16.93\"}]",
                            }
                        ],
                    },
                    "sourceToolAssistantUUID": "a-quote",
                },
                {
                    "type": "assistant",
                    "uuid": "a-final",
                    "timestamp": "2026-02-12T08:27:22Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "招商证券今日收跌。"}],
                    },
                },
            ],
        )

        session = make_session(session_file)
        session.id = "realistic"
        result = agent.export_session(session, output_dir)

        with open(result, encoding="utf-8") as f:
            exported = json.load(f)

        serialized = json.dumps(exported, ensure_ascii=False)
        assert "TodoWrite" not in serialized
        assert "Base directory for this skill" not in serialized
        assert len(exported["messages"]) == 6
        assert exported["messages"][2]["parts"][0]["tool"] == "Skill"
        assert exported["messages"][2]["parts"][0]["state"]["status"] == "success"
        assert exported["messages"][3]["parts"][0]["state"]["output"] == [
            {"type": "text", "text": "{\"iid\":\"600999.SH\"}", "time_created": 1770884831000}
        ]
        assert exported["messages"][4]["parts"][0]["state"]["output"] == [
            {"type": "text", "text": "[{\"最新价\":\"16.93\"}]", "time_created": 1770884835000}
        ]
