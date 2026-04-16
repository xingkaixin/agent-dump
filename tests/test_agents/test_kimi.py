"""
测试 agents/kimi.py 模块
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.kimi import KimiAgent
from agent_dump.paths import ProviderRoots


def write_metadata(
    session_dir: Path,
    *,
    session_id: str = "test-session",
    title: str = "Test Session",
    wire_mtime: float | None = None,
    title_generated: bool = False,
) -> Path:
    """写入 metadata.json。"""
    metadata = {
        "session_id": session_id,
        "title": title,
        "wire_mtime": wire_mtime or datetime.now().timestamp(),
        "title_generated": title_generated,
    }
    metadata_path = session_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata_path


def write_jsonl(file_path: Path, records: list[dict]) -> None:
    """写入 jsonl 文件。"""
    content = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    file_path.write_text(f"{content}\n", encoding="utf-8")


def make_session(session_dir: Path, session_id: str = "test-session", title: str = "Test Session") -> Session:
    """构造测试用 Session。"""
    now = datetime.now()
    return Session(
        id=session_id,
        title=title,
        created_at=now,
        updated_at=now,
        source_path=session_dir,
        metadata={},
    )


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

    def test_find_base_path_uses_kimi_share_dir(self, monkeypatch, tmp_path):
        """测试优先使用 KIMI_SHARE_DIR/sessions"""
        agent = KimiAgent()
        kimi_root = tmp_path / "kimi-root"
        sessions_dir = kimi_root / "sessions"
        sessions_dir.mkdir(parents=True)

        monkeypatch.setenv("KIMI_SHARE_DIR", str(kimi_root))
        result = agent._find_base_path()

        assert result == sessions_dir

    def test_find_base_path_falls_back_to_local_dev(self, monkeypatch, tmp_path):
        """测试回退到本地开发目录 data/kimi"""
        agent = KimiAgent()
        monkeypatch.chdir(tmp_path)
        local_dev_path = tmp_path / "data" / "kimi"
        local_dev_path.mkdir(parents=True)

        roots = ProviderRoots(
            codex_root=tmp_path / ".codex",
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / "missing-kimi-root",
            opencode_root=tmp_path / ".local" / "share" / "opencode",
        )

        with mock.patch("agent_dump.agents.kimi.ProviderRoots.from_env_or_home", return_value=roots):
            result = agent._find_base_path()

        assert result == Path("data/kimi")

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
        session_dir = sessions_dir / "project1" / "session1"
        session_dir.mkdir(parents=True)
        (session_dir / "metadata.json").touch()

        with mock.patch.object(agent, "_find_base_path", return_value=sessions_dir):
            result = agent.is_available()

        assert result is True

    def test_resolve_cwd_from_project_hash_returns_path_when_matched(self, tmp_path):
        """测试能正确从 kimi.json 解析 project hash 对应的 cwd"""
        agent = KimiAgent()
        agent.base_path = tmp_path / "sessions"

        kimi_root = agent.base_path.parent
        kimi_root.mkdir(parents=True, exist_ok=True)
        real_cwd = "/workspace/demo-project"
        project_hash = hashlib.md5(real_cwd.encode("utf-8")).hexdigest()

        kimi_json = {
            "work_dirs": [
                {"path": "/other/project", "kaos": "local"},
                {"path": real_cwd, "kaos": "local"},
            ]
        }
        (kimi_root / "kimi.json").write_text(json.dumps(kimi_json), encoding="utf-8")

        result = agent._resolve_cwd_from_project_hash(project_hash)
        assert result == real_cwd

    def test_resolve_cwd_from_project_hash_returns_none_when_no_kimi_json(self, tmp_path):
        """测试没有 kimi.json 时返回 None"""
        agent = KimiAgent()
        agent.base_path = tmp_path / "sessions"
        result = agent._resolve_cwd_from_project_hash("anyhash")
        assert result is None

    def test_resolve_cwd_from_project_hash_returns_none_when_no_match(self, tmp_path):
        """测试 kimi.json 中没有匹配项时返回 None"""
        agent = KimiAgent()
        agent.base_path = tmp_path / "sessions"

        kimi_root = agent.base_path.parent
        kimi_root.mkdir(parents=True, exist_ok=True)
        kimi_json = {"work_dirs": [{"path": "/other/project", "kaos": "local"}]}
        (kimi_root / "kimi.json").write_text(json.dumps(kimi_json), encoding="utf-8")

        result = agent._resolve_cwd_from_project_hash("nomatchhash")
        assert result is None

    def test_parse_session_includes_cwd_from_kimi_json(self, tmp_path):
        """测试 _parse_session 会把真实 cwd 存入 metadata"""
        agent = KimiAgent()
        agent.base_path = tmp_path / "sessions"

        real_cwd = "/workspace/demo-project"
        project_hash = hashlib.md5(real_cwd.encode("utf-8")).hexdigest()
        session_dir = agent.base_path / project_hash / "session1"
        session_dir.mkdir(parents=True)

        kimi_json = {"work_dirs": [{"path": real_cwd, "kaos": "local"}]}
        (tmp_path / "kimi.json").write_text(json.dumps(kimi_json), encoding="utf-8")

        metadata_path = write_metadata(session_dir, session_id="s1")
        write_jsonl(session_dir / "context.jsonl", [{"role": "user", "content": "hi"}])

        result = agent._parse_session(metadata_path)
        assert result is not None
        assert result.metadata.get("cwd") == real_cwd

    def test_get_session_head_uses_cwd_from_metadata(self, tmp_path):
        """测试 get_session_head 优先使用 metadata 中的真实 cwd"""
        agent = KimiAgent()
        session_dir = tmp_path / "hash" / "session1"
        session_dir.mkdir(parents=True)
        context_path = session_dir / "context.jsonl"
        write_jsonl(context_path, [{"role": "user"}])

        session = Session(
            id="test-session",
            title="Test Session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_dir,
            metadata={"context_file": str(context_path), "wire_file": None, "cwd": "/real/cwd"},
        )

        head = agent.get_session_head(session)
        assert head["cwd_or_project"] == "/real/cwd"

    def test_parse_session_with_context_only(self, tmp_path):
        """测试仅有 context.jsonl 也能解析会话"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        metadata_path = write_metadata(
            session_dir,
            session_id="context-session",
            title="Context Session",
            title_generated=True,
        )
        write_jsonl(session_dir / "context.jsonl", [{"role": "user", "content": "hello"}])

        result = agent._parse_session(metadata_path)

        assert result is not None
        assert isinstance(result, Session)
        assert result.id == "context-session"
        assert result.title == "Context Session"
        assert result.created_at.tzinfo == timezone.utc
        assert result.metadata["context_file"] == str(session_dir / "context.jsonl")
        assert result.metadata["wire_file"] is None
        assert result.metadata["title_generated"] is True

    def test_parse_session_with_wire_only(self, tmp_path):
        """测试仅有 wire.jsonl 也能解析会话"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        metadata_path = write_metadata(session_dir, session_id="wire-session")
        (session_dir / "wire.jsonl").touch()

        result = agent._parse_session(metadata_path)

        assert result is not None
        assert result.id == "wire-session"
        assert result.created_at.tzinfo == timezone.utc
        assert result.metadata["context_file"] is None
        assert result.metadata["wire_file"] == str(session_dir / "wire.jsonl")

    def test_parse_session_parses_wire_mtime_as_utc(self, tmp_path):
        """测试 wire_mtime 会被解析为 UTC aware datetime"""
        agent = KimiAgent()
        session_dir = tmp_path / "session-utc"
        session_dir.mkdir()

        metadata_path = write_metadata(
            session_dir,
            session_id="utc-session",
            wire_mtime=datetime(2025, 3, 5, 2, 0, tzinfo=timezone.utc).timestamp(),
        )
        (session_dir / "wire.jsonl").touch()

        result = agent._parse_session(metadata_path)

        assert result is not None
        assert result.created_at == datetime(2025, 3, 5, 2, 0, tzinfo=timezone.utc)

    def test_parse_session_no_context_and_no_wire(self, tmp_path):
        """测试既没有 context 也没有 wire 时返回 None"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        metadata_path = write_metadata(session_dir)

        result = agent._parse_session(metadata_path)

        assert result is None

    def test_parse_session_invalid_json(self, tmp_path):
        """测试无效的 JSON 返回 None"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        metadata_path = session_dir / "metadata.json"
        metadata_path.write_text("invalid json", encoding="utf-8")
        (session_dir / "wire.jsonl").touch()

        result = agent._parse_session(metadata_path)

        assert result is None

    def test_get_sessions_filtered_by_days(self, tmp_path):
        """测试按天数过滤会话"""
        agent = KimiAgent()
        agent.base_path = tmp_path

        old_session_dir = tmp_path / "old"
        new_session_dir = tmp_path / "new"
        old_session_dir.mkdir()
        new_session_dir.mkdir()

        write_metadata(
            old_session_dir,
            session_id="old-session",
            title="Old",
            wire_mtime=(datetime.now() - timedelta(days=10)).timestamp(),
        )
        write_jsonl(old_session_dir / "context.jsonl", [{"role": "user", "content": "old"}])

        write_metadata(
            new_session_dir,
            session_id="new-session",
            title="New",
            wire_mtime=datetime.now().timestamp(),
        )
        (new_session_dir / "wire.jsonl").touch()

        result = agent.get_sessions(days=7)

        assert len(result) == 1
        assert result[0].id == "new-session"

    def test_get_sessions_sorted_by_time(self, tmp_path):
        """测试会话按时间倒序排列"""
        agent = KimiAgent()
        agent.base_path = tmp_path

        now = datetime.now()
        yesterday = now - timedelta(days=1)

        session1_dir = tmp_path / "session1"
        session2_dir = tmp_path / "session2"
        session1_dir.mkdir()
        session2_dir.mkdir()

        write_metadata(
            session1_dir,
            session_id="session-001",
            title="Yesterday",
            wire_mtime=yesterday.timestamp(),
        )
        write_jsonl(session1_dir / "context.jsonl", [{"role": "user", "content": "y"}])

        write_metadata(
            session2_dir,
            session_id="session-002",
            title="Today",
            wire_mtime=now.timestamp(),
        )
        (session2_dir / "wire.jsonl").touch()

        result = agent.get_sessions(days=7)

        assert len(result) == 2
        assert result[0].id == "session-002"
        assert result[1].id == "session-001"

    def test_export_session_no_context_or_wire(self, tmp_path):
        """测试没有 context 和 wire 时导出报错"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        session = make_session(session_dir)

        with pytest.raises(FileNotFoundError):
            agent.export_session(session, tmp_path)

    def test_get_session_head_counts_raw_lines(self, tmp_path):
        """测试 get_session_head 返回 Kimi 轻量摘要。"""
        agent = KimiAgent()
        session_dir = tmp_path / "project1" / "session1"
        session_dir.mkdir(parents=True)
        context_path = session_dir / "context.jsonl"
        write_jsonl(context_path, [{"role": "user"}, {"role": "assistant"}])

        session = Session(
            id="test-session",
            title="Test Session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=session_dir,
            metadata={"context_file": str(context_path), "wire_file": None},
        )

        head = agent.get_session_head(session)

        assert head["cwd_or_project"] == str(session_dir)
        assert head["message_count"] == 2

    def test_export_raw_session_prefers_context_file(self, tmp_path):
        """测试 raw 导出优先使用 context.jsonl"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        context_path = session_dir / "context.jsonl"
        wire_path = session_dir / "wire.jsonl"
        context_path.write_text("{\"role\":\"user\"}\n", encoding="utf-8")
        wire_path.write_text("{\"wire\":true}\n", encoding="utf-8")

        session = Session(
            id="test-session",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_dir,
            metadata={"context_file": str(context_path), "wire_file": str(wire_path)},
        )

        result = agent.export_raw_session(session, tmp_path)

        assert result.name == "test-session.raw.jsonl"
        assert result.read_text(encoding="utf-8") == context_path.read_text(encoding="utf-8")

    def test_export_raw_session_falls_back_to_wire_file(self, tmp_path):
        """测试 raw 导出在没有 context 时回退到 wire.jsonl"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        wire_path = session_dir / "wire.jsonl"
        wire_path.write_text("{\"wire\":true}\n", encoding="utf-8")

        session = Session(
            id="test-session",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_dir,
            metadata={"context_file": None, "wire_file": str(wire_path)},
        )

        result = agent.export_raw_session(session, tmp_path)

        assert result.name == "test-session.raw.jsonl"
        assert result.read_text(encoding="utf-8") == wire_path.read_text(encoding="utf-8")

    def test_export_raw_session_raises_when_no_raw_file(self, tmp_path):
        """测试 raw 导出在没有原始文件时抛错"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()

        session = Session(
            id="test-session",
            title="Test Session",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=session_dir,
            metadata={"context_file": None, "wire_file": None},
        )

        with pytest.raises(FileNotFoundError):
            agent.export_raw_session(session, tmp_path)

    def test_get_session_data_from_context_user_message(self, tmp_path):
        """测试 context user 记录正确转换"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(session_dir / "context.jsonl", [{"role": "user", "content": "Hello Kimi"}])

        session = make_session(session_dir)
        result = agent._get_session_data_from_context(session)

        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["parts"] == [{"type": "text", "text": "Hello Kimi", "time_created": 0}]

    def test_context_assistant_tool_outputs_are_backfilled_to_tool_parts(self, tmp_path):
        """测试 assistant 的 tool output 会按 tool_call_id 回填"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "think", "think": "先分析一下"},
                        {"type": "text", "text": "开始处理"},
                    ],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call-001",
                            "function": {
                                "name": "read_file",
                                "arguments": "{\"path\": \"/workspace/a.py\"}",
                            },
                        },
                        {
                            "type": "function",
                            "id": "call-002",
                            "function": {
                                "name": "shell",
                                "arguments": "{\"cmd\": \"pwd\"}",
                            },
                        },
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-001",
                    "content": [
                        {"type": "text", "text": "<system>read ok</system>"},
                        {"type": "text", "text": "file body"},
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-002",
                    "content": "workspace path",
                },
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert result["stats"]["message_count"] == 1
        assert len(result["messages"]) == 1
        message = result["messages"][0]
        assert message["role"] == "assistant"
        assert [part["type"] for part in message["parts"]] == ["reasoning", "text", "tool", "tool"]
        assert message["parts"][2]["state"]["arguments"] == {"path": "/workspace/a.py"}
        assert message["parts"][2]["state"]["output"] == [
            {"type": "text", "text": "<system>read ok</system>", "time_created": 0},
            {"type": "text", "text": "file body", "time_created": 0},
        ]
        assert message["parts"][3]["state"]["output"] == [
            {"type": "text", "text": "workspace path", "time_created": 0}
        ]

    def test_context_tool_record_with_missing_call_id_becomes_fallback_tool_message(self, tmp_path):
        """测试缺少 tool_call_id 时退化为 fallback tool 消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {"role": "assistant", "content": [{"type": "text", "text": "hi"}], "tool_calls": []},
                {"role": "tool", "content": "orphan output"},
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert len(result["messages"]) == 2
        assert result["messages"][1]["role"] == "tool"
        assert result["messages"][1]["parts"] == [
            {"type": "text", "text": "orphan output", "time_created": 0}
        ]

    def test_context_tool_record_with_unknown_tool_call_id_becomes_fallback_tool_message(self, tmp_path):
        """测试未知 tool_call_id 时退化为 fallback tool 消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call-001",
                            "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-999", "content": "unknown output"},
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert len(result["messages"]) == 2
        assert result["messages"][1]["role"] == "tool"
        assert result["messages"][1]["tool_call_id"] == "call-999"

    def test_get_session_data_from_context_ignores_checkpoint_and_usage(self, tmp_path):
        """测试 _checkpoint 和 _usage 不进入导出消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {"role": "_checkpoint", "id": 1},
                {"role": "_usage", "token_count": 123},
                {"role": "user", "content": "real user"},
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["stats"]["message_count"] == 1

    def test_get_session_data_from_context_parses_tool_arguments_json_string(self, tmp_path):
        """测试 tool arguments 的 JSON 字符串会被解析"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call-001",
                            "function": {
                                "name": "shell",
                                "arguments": "{\"cmd\": \"ls\", \"cwd\": \"/workspace\"}",
                            },
                        }
                    ],
                }
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        message = result["messages"][0]
        assert message["mode"] == "tool"
        assert message["parts"][0]["state"]["arguments"] == {"cmd": "ls", "cwd": "/workspace"}
        assert message["parts"][0]["state"]["output"] is None

    def test_get_session_data_from_context_keeps_raw_tool_arguments_when_invalid_json(self, tmp_path):
        """测试非法 JSON 参数保留原始字符串"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        raw_arguments = '{"cmd": "ls"'
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call-001",
                            "function": {
                                "name": "shell",
                                "arguments": raw_arguments,
                            },
                        }
                    ],
                }
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert result["messages"][0]["parts"][0]["state"]["arguments"] == raw_arguments

    def test_context_tool_titles_are_mapped(self, tmp_path):
        """测试 context 中已知工具 title 会被统一映射"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        tool_names = ["ReadFile", "Glob", "StrReplaceFile", "Grep", "WriteFile", "Shell"]
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": f"call-{index}",
                            "function": {"name": name, "arguments": "{}"},
                        }
                        for index, name in enumerate(tool_names, start=1)
                    ],
                }
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert [part["title"] for part in result["messages"][0]["parts"]] == [
            "read",
            "glob",
            "edit",
            "grep",
            "write",
            "bash",
        ]

    def test_unknown_tool_title_keeps_original_name(self, tmp_path):
        """测试未知工具名默认保留原名"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call-001",
                            "function": {"name": "UnknownTool", "arguments": "{}"},
                        }
                    ],
                }
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert result["messages"][0]["parts"][0]["title"] == "UnknownTool"

    def test_context_set_todo_list_tool_call_is_ignored(self, tmp_path):
        """测试 context 中 SetTodoList 不会生成 tool part"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "继续处理"}],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "todo-001",
                            "function": {
                                "name": "SetTodoList",
                                "arguments": "{\"items\": [\"a\"]}",
                            },
                        }
                    ],
                }
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert len(result["messages"]) == 1
        assert result["messages"][0]["parts"] == [
            {"type": "text", "text": "继续处理", "time_created": 0}
        ]

    def test_context_set_todo_list_tool_output_is_dropped(self, tmp_path):
        """测试 context 中 SetTodoList 的 output 会被直接丢弃"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "继续处理"}],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "todo-001",
                            "function": {
                                "name": "SetTodoList",
                                "arguments": "{\"items\": [\"a\"]}",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "todo-001",
                    "content": "<system>Todo list updated</system>",
                },
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        assert len(result["messages"]) == 1
        assert all(message["role"] != "tool" for message in result["messages"])
        assert "Todo list updated" not in json.dumps(result, ensure_ascii=False)

    def test_context_non_ignored_tools_still_backfill_output(self, tmp_path):
        """测试 context 混合 SetTodoList 和正常工具时只保留正常工具"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {
                    "role": "assistant",
                    "content": [{"type": "think", "think": "分析"}],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "read-001",
                            "function": {
                                "name": "ReadFile",
                                "arguments": "{\"path\": \"src/main.py\"}",
                            },
                        },
                        {
                            "type": "function",
                            "id": "todo-001",
                            "function": {
                                "name": "SetTodoList",
                                "arguments": "{\"items\": [\"a\"]}",
                            },
                        },
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "read-001",
                    "content": "<system>read ok</system>",
                },
                {
                    "role": "tool",
                    "tool_call_id": "todo-001",
                    "content": "<system>Todo list updated</system>",
                },
            ],
        )

        result = agent._get_session_data_from_context(make_session(session_dir))

        message = result["messages"][0]
        assert [part["type"] for part in message["parts"]] == ["reasoning", "tool"]
        assert message["parts"][1]["tool"] == "ReadFile"
        assert message["parts"][1]["title"] == "read"
        assert message["parts"][1]["state"]["output"] == [
            {"type": "text", "text": "<system>read ok</system>", "time_created": 0}
        ]
        assert "SetTodoList" not in json.dumps(result, ensure_ascii=False)

    def test_wire_rebuilds_single_assistant_message_from_content_and_tool_calls(self, tmp_path):
        """测试 wire 会把 content 和 tool call 聚合为一条 assistant 消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": 1.0,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                    },
                },
                {
                    "timestamp": 2.0,
                    "message": {
                        "type": "ContentPart",
                        "payload": {"type": "think", "think": "Thinking"},
                    },
                },
                {
                    "timestamp": 3.0,
                    "message": {
                        "type": "ContentPart",
                        "payload": {"type": "text", "text": "Answer"},
                    },
                },
                {
                    "timestamp": 4.0,
                    "message": {
                        "type": "ToolCall",
                        "payload": {
                            "type": "function",
                            "id": "call-001",
                            "function": {"name": "read_file", "arguments": "{\"path\": \"/workspace/a.py\"}"},
                        },
                    },
                },
                {
                    "timestamp": 5.0,
                    "message": {
                        "type": "ToolResult",
                        "payload": {
                            "tool_call_id": "call-001",
                            "return_value": {"content": "file body"},
                        },
                    },
                },
            ],
        )

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assert result["stats"]["message_count"] == 2
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "user"
        assistant = result["messages"][1]
        assert assistant["role"] == "assistant"
        assert [part["type"] for part in assistant["parts"]] == ["reasoning", "text", "tool"]
        assert assistant["parts"][2]["state"]["output"] == [
            {
                "type": "text",
                "text": json.dumps({"content": "file body"}, ensure_ascii=False, indent=2),
                "time_created": 0,
            }
        ]

    def test_wire_tool_call_part_appends_arguments_to_open_call(self, tmp_path):
        """测试 wire ToolCallPart 会把参数碎片拼回对应 tool call"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": 1.0,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                    },
                },
                {
                    "timestamp": 2.0,
                    "message": {
                        "type": "ToolCall",
                        "payload": {
                            "type": "function",
                            "id": "call-001",
                            "function": {"name": "read_file", "arguments": "{\"path"},
                        },
                    },
                },
                {
                    "timestamp": 3.0,
                    "message": {
                        "type": "ToolCallPart",
                        "payload": {"arguments_part": "\": \"/workspace/a.py\"}"},
                    },
                },
            ],
        )

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assistant = result["messages"][1]
        assert assistant["parts"][0]["state"]["arguments"] == {"path": "/workspace/a.py"}

    def test_wire_tool_titles_are_mapped(self, tmp_path):
        """测试 wire 中已知工具 title 会被统一映射"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        tool_names = ["ReadFile", "Glob", "StrReplaceFile", "Grep", "WriteFile", "Shell"]
        records: list[dict[str, object]] = [
            {
                "timestamp": 1.0,
                "message": {
                    "type": "TurnBegin",
                    "payload": {"user_input": [{"text": "Hello"}]},
                },
            }
        ]
        tool_call_records: list[dict[str, object]] = [
            {
                "timestamp": float(index + 1),
                "message": {
                    "type": "ToolCall",
                    "payload": {
                        "type": "function",
                        "id": f"call-{index}",
                        "function": {"name": name, "arguments": "{}"},
                    },
                },
            }
            for index, name in enumerate(tool_names, start=1)
        ]
        records.extend(tool_call_records)
        write_jsonl(session_dir / "wire.jsonl", records)

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assistant = result["messages"][1]
        assert [part["title"] for part in assistant["parts"]] == [
            "read",
            "glob",
            "edit",
            "grep",
            "write",
            "bash",
        ]

    def test_wire_set_todo_list_tool_call_is_ignored(self, tmp_path):
        """测试 wire 中只有 SetTodoList 时不会留下空 assistant 消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": 1.0,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                    },
                },
                {
                    "timestamp": 2.0,
                    "message": {
                        "type": "ToolCall",
                        "payload": {
                            "type": "function",
                            "id": "todo-001",
                            "function": {"name": "SetTodoList", "arguments": "{\"items\": [\"a\"]}"},
                        },
                    },
                },
                {
                    "timestamp": 3.0,
                    "message": {
                        "type": "ToolResult",
                        "payload": {
                            "tool_call_id": "todo-001",
                            "return_value": "<system>Todo list updated</system>",
                        },
                    },
                },
            ],
        )

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"

    def test_wire_set_todo_list_tool_result_is_dropped(self, tmp_path):
        """测试 wire 中 SetTodoList 的 result 不会变成 fallback 消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": 1.0,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                    },
                },
                {
                    "timestamp": 2.0,
                    "message": {
                        "type": "ContentPart",
                        "payload": {"type": "text", "text": "继续处理"},
                    },
                },
                {
                    "timestamp": 3.0,
                    "message": {
                        "type": "ToolCall",
                        "payload": {
                            "type": "function",
                            "id": "todo-001",
                            "function": {"name": "SetTodoList", "arguments": "{\"items\": [\"a\"]}"},
                        },
                    },
                },
                {
                    "timestamp": 4.0,
                    "message": {
                        "type": "ToolResult",
                        "payload": {
                            "tool_call_id": "todo-001",
                            "return_value": "<system>Todo list updated</system>",
                        },
                    },
                },
            ],
        )

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assert len(result["messages"]) == 2
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][1]["parts"] == [
            {"type": "text", "text": "继续处理", "time_created": 2000}
        ]
        assert "Todo list updated" not in json.dumps(result, ensure_ascii=False)

    def test_wire_non_ignored_tools_still_work_with_mapping(self, tmp_path):
        """测试 wire 混合 SetTodoList 和正常工具时正常工具仍可回填"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": 1.0,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                    },
                },
                {
                    "timestamp": 2.0,
                    "message": {
                        "type": "ContentPart",
                        "payload": {"type": "think", "think": "分析"},
                    },
                },
                {
                    "timestamp": 3.0,
                    "message": {
                        "type": "ToolCall",
                        "payload": {
                            "type": "function",
                            "id": "read-001",
                            "function": {"name": "ReadFile", "arguments": "{\"path\": \"src/main.py\"}"},
                        },
                    },
                },
                {
                    "timestamp": 4.0,
                    "message": {
                        "type": "ToolCall",
                        "payload": {
                            "type": "function",
                            "id": "todo-001",
                            "function": {"name": "SetTodoList", "arguments": "{\"items\": [\"a\"]}"},
                        },
                    },
                },
                {
                    "timestamp": 5.0,
                    "message": {
                        "type": "ToolResult",
                        "payload": {
                            "tool_call_id": "read-001",
                            "return_value": "<system>read ok</system>",
                        },
                    },
                },
                {
                    "timestamp": 6.0,
                    "message": {
                        "type": "ToolResult",
                        "payload": {
                            "tool_call_id": "todo-001",
                            "return_value": "<system>Todo list updated</system>",
                        },
                    },
                },
            ],
        )

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assistant = result["messages"][1]
        assert [part["type"] for part in assistant["parts"]] == ["reasoning", "tool"]
        assert assistant["parts"][1]["tool"] == "ReadFile"
        assert assistant["parts"][1]["title"] == "read"
        assert assistant["parts"][1]["state"]["output"] == [
            {"type": "text", "text": "<system>read ok</system>", "time_created": 0}
        ]
        assert "SetTodoList" not in json.dumps(result, ensure_ascii=False)

    def test_wire_ignores_step_begin_status_update_and_approval_events(self, tmp_path):
        """测试 wire 内部状态事件不会导出为消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": 1.0,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                    },
                },
                {"timestamp": 2.0, "message": {"type": "StepBegin", "payload": {"n": 1}}},
                {"timestamp": 3.0, "message": {"type": "StatusUpdate", "payload": {"token_usage": {"input_tokens": 1}}}},
                {"timestamp": 4.0, "message": {"type": "ApprovalRequest", "payload": {"id": "a"}}},
                {"timestamp": 5.0, "message": {"type": "ApprovalResponse", "payload": {"id": "a"}}},
                {"timestamp": 6.0, "message": {"type": "TurnEnd", "payload": {}}},
            ],
        )

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"

    def test_wire_unmatched_tool_result_becomes_fallback_tool_message(self, tmp_path):
        """测试 wire 无法关联的 ToolResult 会退化为 fallback tool 消息"""
        agent = KimiAgent()
        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": 1.0,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                    },
                },
                {
                    "timestamp": 2.0,
                    "message": {
                        "type": "ToolResult",
                        "payload": {
                            "tool_call_id": "missing-call",
                            "return_value": {"error": "not found"},
                        },
                    },
                },
            ],
        )

        result = agent._get_session_data_from_wire(make_session(session_dir))

        assert len(result["messages"]) == 2
        assert result["messages"][1]["role"] == "tool"
        assert result["messages"][1]["tool_call_id"] == "missing-call"

    def test_export_session_valid_uses_context_when_present(self, tmp_path):
        """测试导出优先使用 context 主路径且回填 tool output"""
        agent = KimiAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {"role": "_checkpoint", "id": 0},
                {"role": "user", "content": "Hello Kimi"},
                {
                    "role": "assistant",
                    "content": [{"type": "think", "think": "分析"}, {"type": "text", "text": "回答"}],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call-001",
                            "function": {"name": "read_file", "arguments": "{\"path\": \"/workspace/x.py\"}"},
                        }
                    ],
                },
                {"role": "tool", "content": "tool result", "tool_call_id": "call-001"},
                {"role": "_usage", "token_count": 999},
            ],
        )

        session = make_session(session_dir, session_id="context-session", title="Context Session")
        result = agent.export_session(session, output_dir)

        exported = json.loads(result.read_text(encoding="utf-8"))
        assert exported["id"] == "context-session"
        assert exported["title"] == "Context Session"
        assert exported["stats"]["message_count"] == 2
        assert len(exported["messages"]) == 2
        assert exported["messages"][0]["role"] == "user"
        assert exported["messages"][1]["role"] == "assistant"
        assert exported["messages"][1]["parts"][2]["state"]["output"] == [
            {"type": "text", "text": "tool result", "time_created": 0}
        ]

    def test_export_session_creates_missing_output_dir(self, tmp_path):
        """测试导出时会自动创建缺失的输出目录"""
        agent = KimiAgent()
        output_dir = tmp_path / "nested" / "output"

        session_dir = tmp_path / "session-create-dir"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {"role": "user", "content": "Hello Kimi"},
                {"role": "assistant", "content": [{"type": "text", "text": "回答"}]},
            ],
        )

        session = make_session(session_dir, session_id="test-create-dir", title="Create Dir")
        result = agent.export_session(session, output_dir)

        assert output_dir.exists()
        assert result.exists()

    def test_export_session_extracts_tokens(self, tmp_path):
        """测试导出时提取 token 使用情况"""
        agent = KimiAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": datetime.now().timestamp(),
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                        "usage": {"input_tokens": 10, "output_tokens": 20},
                    },
                }
            ],
        )

        session = make_session(session_dir, session_id="test", title="Test")
        result = agent.export_session(session, output_dir)

        exported = json.loads(result.read_text(encoding="utf-8"))
        assert exported["stats"]["total_input_tokens"] == 10
        assert exported["stats"]["total_output_tokens"] == 20
        assert exported["stats"]["total_tokens"] == 0

    def test_export_session_uses_last_usage_token_count_from_context(self, tmp_path):
        """测试导出时从 context.jsonl 的最后一条 _usage 提取会话总 token"""
        agent = KimiAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {"role": "user", "content": "Hello"},
                {"role": "_usage", "token_count": 100},
                {"role": "assistant", "content": [{"type": "text", "text": "World"}]},
                {"role": "_usage", "token_count": 250},
                {"role": "_usage", "token_count": 999},
            ],
        )
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": datetime.now().timestamp(),
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                        "usage": {"input_tokens": 10, "output_tokens": 20},
                    },
                },
                {"role": "_usage", "token_count": 12345},
            ],
        )

        session = make_session(session_dir, session_id="test", title="Test")
        result = agent.export_session(session, output_dir)

        exported = json.loads(result.read_text(encoding="utf-8"))
        assert exported["stats"]["total_input_tokens"] == 10
        assert exported["stats"]["total_output_tokens"] == 20
        assert exported["stats"]["total_tokens"] == 999

    def test_export_session_total_tokens_defaults_to_zero_without_usage(self, tmp_path):
        """测试没有 _usage 时会话总 token 默认为 0"""
        agent = KimiAgent()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        session_dir = tmp_path / "session1"
        session_dir.mkdir()
        write_jsonl(
            session_dir / "context.jsonl",
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": [{"type": "text", "text": "World"}]},
            ],
        )
        write_jsonl(
            session_dir / "wire.jsonl",
            [
                {
                    "timestamp": datetime.now().timestamp(),
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"text": "Hello"}]},
                        "usage": {"input_tokens": 10, "output_tokens": 20},
                    },
                }
            ],
        )

        session = make_session(session_dir, session_id="test", title="Test")
        result = agent.export_session(session, output_dir)

        exported = json.loads(result.read_text(encoding="utf-8"))
        assert exported["stats"]["total_input_tokens"] == 10
        assert exported["stats"]["total_output_tokens"] == 20
        assert exported["stats"]["total_tokens"] == 0
