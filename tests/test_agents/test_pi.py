"""测试 agents/pi.py 模块。"""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest import mock

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
