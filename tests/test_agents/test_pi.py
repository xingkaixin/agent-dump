"""测试 agents/pi.py 模块。"""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.pi import PiAgent
from agent_dump.paths import ProviderRoots


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


class TestPiAgent:
    """测试 PiAgent 类。"""

    def test_init(self):
        agent = PiAgent()

        assert agent.name == "pi"
        assert agent.display_name == "Pi"
        assert agent.base_path is None

    def test_find_base_path_uses_pi_home_env(self, monkeypatch, tmp_path):
        agent = PiAgent()
        pi_home = tmp_path / "pi-home"
        sessions_dir = pi_home / "agent" / "sessions"
        sessions_dir.mkdir(parents=True)

        monkeypatch.setenv("PI_HOME", str(pi_home))
        result = agent._find_base_path()

        assert result == sessions_dir

    def test_find_base_path_falls_back_to_local_dev(self, monkeypatch, tmp_path):
        agent = PiAgent()
        monkeypatch.chdir(tmp_path)
        local_dev_path = tmp_path / "data" / "pi"
        local_dev_path.mkdir(parents=True)

        roots = ProviderRoots(
            codex_root=tmp_path / ".codex",
            claude_root=tmp_path / ".claude",
            kimi_root=tmp_path / ".kimi",
            opencode_root=tmp_path / ".local" / "share" / "opencode",
            pi_root=tmp_path / "missing-pi-root",
        )

        with mock.patch("agent_dump.agents.pi.ProviderRoots.from_env_or_home", return_value=roots):
            result = agent._find_base_path()

        assert result == Path("data/pi")

    def test_is_available_requires_jsonl_file(self, tmp_path):
        agent = PiAgent()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        with mock.patch.object(agent, "_find_base_path", return_value=sessions_dir):
            assert agent.is_available() is False

        (sessions_dir / "session.jsonl").touch()

        with mock.patch.object(agent, "_find_base_path", return_value=sessions_dir):
            assert agent.is_available() is True

    def test_find_session_by_id_locates_file_by_suffix(self, tmp_path):
        """测试按文件名后缀（日期前缀 + id）直接定位会话"""
        agent = PiAgent()
        agent.base_path = tmp_path
        now = datetime.now(timezone.utc)
        session_path = tmp_path / "--workspace--" / "20260101_pi-session.jsonl"
        session_path.parent.mkdir()
        _write_jsonl(
            session_path,
            [
                {
                    "type": "session",
                    "version": 3,
                    "id": "pi-session",
                    "timestamp": now.isoformat(),
                    "cwd": "/workspace/pi",
                }
            ],
        )

        found = agent.find_session_by_id("pi-session")

        assert found is not None
        assert found.id == "pi-session"
        assert found.source_path == session_path
        assert agent.find_session_by_id("missing") is None

    def test_parse_session_file_valid(self, tmp_path):
        agent = PiAgent()
        now = datetime.now(timezone.utc)
        session_path = tmp_path / "--workspace--" / "20260101_pi-session.jsonl"
        session_path.parent.mkdir()
        _write_jsonl(
            session_path,
            [
                {
                    "type": "session",
                    "version": 3,
                    "id": "pi-session",
                    "timestamp": now.isoformat(),
                    "cwd": "/workspace/pi",
                },
                {
                    "type": "message",
                    "id": "user1",
                    "parentId": None,
                    "timestamp": now.isoformat(),
                    "message": {
                        "role": "user",
                        "content": "Build Pi support",
                        "timestamp": int(now.timestamp() * 1000),
                    },
                },
                {
                    "type": "session_info",
                    "id": "info1",
                    "parentId": "user1",
                    "timestamp": now.isoformat(),
                    "name": "Pi Support",
                },
                {
                    "type": "message",
                    "id": "assistant1",
                    "parentId": "user1",
                    "timestamp": now.isoformat(),
                    "message": {
                        "role": "assistant",
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-5",
                        "content": [{"type": "text", "text": "Pi answer"}],
                        "usage": {
                            "input": 10,
                            "output": 5,
                            "totalTokens": 15,
                            "cost": {"total": 0.01},
                        },
                    },
                },
            ],
        )

        session = agent._parse_session_file(session_path)

        assert session is not None
        assert session.id == "pi-session"
        assert session.title == "Pi Support"
        assert session.metadata["cwd"] == "/workspace/pi"
        assert session.metadata["model"] == "claude-sonnet-4-5"
        assert session.metadata["message_count"] == 2

    def test_get_session_data_converts_pi_entries(self, tmp_path):
        agent = PiAgent()
        now = datetime.now(timezone.utc)
        session_path = tmp_path / "session.jsonl"
        _write_jsonl(
            session_path,
            [
                {"type": "session", "version": 3, "id": "pi-session", "timestamp": now.isoformat(), "cwd": "/work"},
                {
                    "type": "message",
                    "id": "user1",
                    "parentId": None,
                    "timestamp": now.isoformat(),
                    "message": {"role": "user", "content": [{"type": "text", "text": "Pi prompt"}]},
                },
                {
                    "type": "message",
                    "id": "assistant1",
                    "parentId": "user1",
                    "timestamp": now.isoformat(),
                    "message": {
                        "role": "assistant",
                        "provider": "openai",
                        "model": "gpt-5",
                        "content": [
                            {"type": "thinking", "thinking": "Plan"},
                            {"type": "text", "text": "Pi answer"},
                            {"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {"command": "pwd"}},
                        ],
                    },
                },
                {
                    "type": "message",
                    "id": "tool1",
                    "parentId": "assistant1",
                    "timestamp": now.isoformat(),
                    "message": {
                        "role": "toolResult",
                        "toolCallId": "call-1",
                        "toolName": "bash",
                        "content": [{"type": "text", "text": "/work"}],
                        "isError": False,
                    },
                },
                {
                    "type": "compaction",
                    "id": "compact1",
                    "parentId": "tool1",
                    "timestamp": now.isoformat(),
                    "summary": "Older context",
                },
            ],
        )
        session = agent._parse_session_file(session_path)
        assert session is not None

        data = agent.get_session_data(session)

        assert data["id"] == "pi-session"
        assert data["stats"]["message_count"] == 4
        exported = json.dumps(data, ensure_ascii=False)
        assert "Pi prompt" in exported
        assert "Pi answer" in exported
        assert "Older context" in exported
        assert '"tool": "bash"' in exported
        assert data["messages"][1]["parts"][0]["type"] == "reasoning"

    def test_export_session_writes_json(self, tmp_path):
        agent = PiAgent()
        now = datetime.now(timezone.utc)
        session_path = tmp_path / "session.jsonl"
        _write_jsonl(
            session_path,
            [
                {"type": "session", "version": 3, "id": "pi-session", "timestamp": now.isoformat(), "cwd": "/work"},
                {"type": "message", "id": "user1", "message": {"role": "user", "content": "Hello"}},
            ],
        )
        session = agent._parse_session_file(session_path)
        assert session is not None

        output_path = agent.export_session(session, tmp_path / "out")

        assert output_path.name == "pi-session.json"
        assert json.loads(output_path.read_text(encoding="utf-8"))["id"] == "pi-session"


class TestMalformedTimestamps:
    """AD-122：越界的 epoch 值不得让 pi provider 抛异常。"""

    def test_out_of_range_timestamp_yields_none_instead_of_raising(self):
        agent = PiAgent()

        assert agent._parse_datetime(1e30) is None
        assert agent._parse_datetime(-1e30) is None

    def test_normal_millisecond_timestamp_still_parses(self):
        agent = PiAgent()

        assert agent._parse_datetime(1704067200000) == datetime(2024, 1, 1, tzinfo=timezone.utc)


class TestMalformedRecordsDoNotBreakTheSession:
    """AD-160：合法但非对象的记录只跳过该条，前后内容都要保留。"""

    @staticmethod
    def _write(path):
        path.write_text(
            "\n".join(
                [
                    json.dumps({"type": "session", "id": "s1", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/w"}),
                    json.dumps(
                        {
                            "type": "message",
                            "message": {"role": "user", "content": [{"type": "text", "text": "BEFORE"}]},
                        }
                    ),
                    "1",
                    "[]",
                    '"text"',
                    json.dumps(
                        {
                            "type": "message",
                            "message": {"role": "assistant", "content": [{"type": "text", "text": "AFTER"}]},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def test_get_session_data_keeps_records_around_the_bad_ones(self, tmp_path):
        path = tmp_path / "20260101_s1.jsonl"
        self._write(path)
        now = datetime.now(timezone.utc)
        session = Session(id="s1", title="T", created_at=now, updated_at=now, source_path=path, metadata={})

        data = PiAgent().get_session_data(session)

        serialized = json.dumps(data, ensure_ascii=False)
        assert "BEFORE" in serialized
        assert "AFTER" in serialized

    def test_get_session_head_does_not_raise(self, tmp_path):
        path = tmp_path / "20260101_s1.jsonl"
        self._write(path)
        now = datetime.now(timezone.utc)
        session = Session(id="s1", title="T", created_at=now, updated_at=now, source_path=path, metadata={})

        assert PiAgent().get_session_head(session)["message_count"] == 2


class TestPiRecordContracts:
    """AD-163：每种已实现的 Pi entry/role/part 都要有可观察的输出契约。"""

    NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def _write(cls, tmp_path: Path, records: list[dict]) -> Session:
        session_path = tmp_path / "session.jsonl"
        header = {
            "type": "session",
            "version": 3,
            "id": "pi-session",
            "timestamp": cls.NOW.isoformat(),
            "cwd": "/work",
        }
        _write_jsonl(session_path, [header, *records])
        session = PiAgent()._parse_session_file(session_path)
        assert session is not None
        return session

    @classmethod
    def _data(cls, tmp_path: Path, records: list[dict]) -> dict:
        return PiAgent().get_session_data(cls._write(tmp_path, records))

    @classmethod
    def _entry(cls, entry_type: str, **fields) -> dict:
        return {"type": entry_type, "id": fields.pop("id", "e1"), "timestamp": cls.NOW.isoformat(), **fields}

    def test_branch_summary_entry_becomes_a_branch_summary_message(self, tmp_path):
        data = self._data(tmp_path, [self._entry("branch_summary", summary="Branch recap")])

        assert [m["role"] for m in data["messages"]] == ["branch_summary"]
        assert data["messages"][0]["parts"][0]["text"] == "Branch recap"

    def test_branch_summary_message_role_normalizes_the_same_way(self, tmp_path):
        data = self._data(
            tmp_path,
            [self._entry("message", message={"role": "branchSummary", "summary": "Recap via message"})],
        )

        assert [m["role"] for m in data["messages"]] == ["branch_summary"]
        assert data["messages"][0]["parts"][0]["text"] == "Recap via message"

    def test_compaction_summary_message_role_normalizes_to_compaction(self, tmp_path):
        data = self._data(
            tmp_path,
            [self._entry("message", message={"role": "compactionSummary", "summary": "Compacted"})],
        )

        assert [m["role"] for m in data["messages"]] == ["compaction"]

    def test_custom_message_entry_becomes_a_custom_message(self, tmp_path):
        data = self._data(
            tmp_path,
            [self._entry("custom_message", content=[{"type": "text", "text": "Custom note"}])],
        )

        assert [m["role"] for m in data["messages"]] == ["custom"]
        assert data["messages"][0]["parts"][0]["text"] == "Custom note"

    def test_custom_message_role_inside_a_message_entry(self, tmp_path):
        data = self._data(
            tmp_path,
            [self._entry("message", message={"role": "custom", "content": "Inline custom"})],
        )

        assert [m["role"] for m in data["messages"]] == ["custom"]

    def test_bash_execution_becomes_a_tool_message(self, tmp_path):
        data = self._data(
            tmp_path,
            [self._entry("message", message={"role": "bashExecution", "command": "ls -la", "output": "total 0"})],
        )

        assert [m["role"] for m in data["messages"]] == ["tool"]
        serialized = json.dumps(data, ensure_ascii=False)
        assert "ls -la" in serialized
        assert "total 0" in serialized

    def test_bash_execution_without_command_or_output_is_dropped(self, tmp_path):
        data = self._data(
            tmp_path,
            [self._entry("message", message={"role": "bashExecution", "command": "  ", "output": "   "})],
        )

        assert data["messages"] == []

    def test_image_part_keeps_its_mime_type_and_data(self, tmp_path):
        data = self._data(
            tmp_path,
            [
                self._entry(
                    "message",
                    message={
                        "role": "user",
                        "content": [{"type": "image", "mimeType": "image/png", "data": "BASE64"}],
                    },
                )
            ],
        )

        part = data["messages"][0]["parts"][0]
        assert part["type"] == "image"
        assert part["mime_type"] == "image/png"
        assert part["data"] == "BASE64"

    def test_image_part_without_a_mime_type_reports_none(self, tmp_path):
        data = self._data(
            tmp_path,
            [self._entry("message", message={"role": "user", "content": [{"type": "image", "data": "BASE64"}]})],
        )

        assert data["messages"][0]["parts"][0]["mime_type"] is None

    def test_plain_string_content_becomes_one_text_part(self, tmp_path):
        data = self._data(tmp_path, [self._entry("message", message={"role": "user", "content": "just a string"})])

        assert data["messages"][0]["parts"] == [
            {"type": "text", "text": "just a string", "time_created": int(self.NOW.timestamp() * 1000)}
        ]

    @pytest.mark.parametrize("content", ["", "   ", [], [""], [{"type": "text", "text": "  "}], None, 42])
    def test_empty_or_unusable_content_yields_no_message(self, tmp_path, content):
        data = self._data(tmp_path, [self._entry("message", message={"role": "user", "content": content})])

        assert data["messages"] == []

    def test_usage_totals_reach_the_export_stats(self, tmp_path):
        data = self._data(
            tmp_path,
            [
                self._entry(
                    "message",
                    id="a1",
                    message={
                        "role": "assistant",
                        "content": [{"type": "text", "text": "one"}],
                        "usage": {"input": 10, "output": 20, "totalTokens": 30, "cost": {"total": 0.5}},
                    },
                ),
                self._entry(
                    "message",
                    id="a2",
                    message={
                        "role": "assistant",
                        "content": [{"type": "text", "text": "two"}],
                        "usage": {"input": 3, "output": 4, "totalTokens": 7, "cost": {"total": 0.25}},
                    },
                ),
            ],
        )

        stats = data["stats"]
        assert stats["total_input_tokens"] == 13
        assert stats["total_output_tokens"] == 24
        assert stats["total_tokens"] == 37
        assert stats["total_cost"] == pytest.approx(0.75)

    @pytest.mark.parametrize(
        "usage",
        [
            {"input": "many", "output": None, "totalTokens": [1], "cost": {"total": "free"}},
            {"input": True, "output": False, "totalTokens": True, "cost": {"total": True}},
            {"input": 5, "output": 5, "totalTokens": 10, "cost": "not-an-object"},
            "not-an-object",
            None,
        ],
    )
    def test_malformed_usage_leaves_totals_at_zero_without_losing_content(self, tmp_path, usage):
        data = self._data(
            tmp_path,
            [
                self._entry(
                    "message",
                    message={"role": "assistant", "content": [{"type": "text", "text": "kept"}], "usage": usage},
                )
            ],
        )

        assert "kept" in json.dumps(data, ensure_ascii=False)
        assert data["stats"]["total_input_tokens"] in (0, 5)
        assert data["stats"]["total_cost"] == 0

    @pytest.mark.parametrize("entry_type", ["branch_summary", "compaction"])
    def test_summary_entries_without_a_summary_are_dropped(self, tmp_path, entry_type):
        data = self._data(tmp_path, [self._entry(entry_type, summary="   ")])

        assert data["messages"] == []

    def test_custom_message_entry_without_usable_content_is_dropped(self, tmp_path):
        data = self._data(tmp_path, [self._entry("custom_message", content=[{"type": "text", "text": " "}])])

        assert data["messages"] == []

    def test_mixed_content_list_keeps_strings_and_skips_non_objects(self, tmp_path):
        data = self._data(
            tmp_path,
            [
                self._entry(
                    "message",
                    message={
                        "role": "user",
                        "content": ["bare string", 42, None, {"type": "text", "text": "typed"}],
                    },
                )
            ],
        )

        texts = [part["text"] for part in data["messages"][0]["parts"] if part["type"] == "text"]
        assert texts == ["bare string", "typed"], "裸字符串保留，非对象项跳过"

    def test_thinking_fragments_reach_the_head_summary(self, tmp_path):
        session = self._write(
            tmp_path,
            [
                self._entry(
                    "message",
                    message={
                        "role": "assistant",
                        "content": [{"type": "thinking", "thinking": "reasoned"}, {"type": "text", "text": "said"}],
                    },
                )
            ],
        )

        head = PiAgent().get_session_head(session)

        assert head["message_count"] == 1

    def test_session_name_records_retitle_the_session(self, tmp_path):
        data = self._data(
            tmp_path,
            [
                self._entry("session_info", name="First name"),
                self._entry("message", message={"role": "user", "content": "hi"}),
                self._entry("session_info", name="Latest name"),
            ],
        )

        assert data["title"] == "Latest name", "最后一条 session_info 决定标题"

    def test_unknown_entry_types_are_ignored_without_dropping_the_rest(self, tmp_path):
        data = self._data(
            tmp_path,
            [
                self._entry("message", id="m1", message={"role": "user", "content": "before"}),
                self._entry("some_future_type", payload={"anything": True}),
                self._entry("message", id="m2", message={"role": "user", "content": "after"}),
            ],
        )

        serialized = json.dumps(data, ensure_ascii=False)
        assert "before" in serialized
        assert "after" in serialized
        assert data["stats"]["message_count"] == 2

    def test_parent_branching_keeps_every_recorded_message(self, tmp_path):
        """Pi 允许 parentId 分叉；导出保留全部分支，不做树选择。"""
        data = self._data(
            tmp_path,
            [
                self._entry("message", id="root", parentId=None, message={"role": "user", "content": "root"}),
                self._entry("message", id="a", parentId="root", message={"role": "assistant", "content": "branch a"}),
                self._entry("message", id="b", parentId="root", message={"role": "assistant", "content": "branch b"}),
            ],
        )

        serialized = json.dumps(data, ensure_ascii=False)
        assert "branch a" in serialized
        assert "branch b" in serialized
        assert data["stats"]["message_count"] == 3
