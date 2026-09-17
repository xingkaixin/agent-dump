from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from deepchat_fixtures import create_deepchat_db
from locale_helpers import expect
import pytest

from agent_dump.agents.deepchat import DeepChatAgent
from agent_dump.collect_events import extract_collect_events
from agent_dump.diagnostics import DiagnosticCapabilityError
from agent_dump.i18n import Keys
from agent_dump.search_index import SearchIndex


@pytest.fixture
def database(tmp_path):
    return create_deepchat_db(tmp_path / "app_db" / "agent.db", int(datetime.now(timezone.utc).timestamp() * 1000))


@pytest.mark.parametrize(
    ("platform", "env", "relative"),
    [
        ("darwin", {}, "Library/Application Support/DeepChat/app_db/agent.db"),
        ("win32", {}, "AppData/Roaming/DeepChat/app_db/agent.db"),
        ("linux", {}, ".config/DeepChat/app_db/agent.db"),
        ("win32", {"APPDATA": "roaming"}, "roaming/DeepChat/app_db/agent.db"),
        ("linux", {"XDG_CONFIG_HOME": "config"}, "config/DeepChat/app_db/agent.db"),
        ("darwin", {"DEEPCHAT_USER_DATA_DIR": "custom"}, "custom/app_db/agent.db"),
    ],
)
def test_search_roots(platform, env, relative, tmp_path, monkeypatch):
    monkeypatch.setattr("agent_dump.agents.deepchat.sys.platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in ("APPDATA", "XDG_CONFIG_HOME", "DEEPCHAT_USER_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, str(tmp_path / value))
    assert DeepChatAgent().get_search_roots()[0].path == tmp_path / relative


def test_discovery_window_drafts_and_unknown_directory(database):
    agent = DeepChatAgent(database)
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO new_sessions SELECT 'old', agent_id, 'Old', NULL, 0, session_kind, NULL, 0, 0 FROM new_sessions"
        )
        conn.execute(
            "INSERT INTO new_sessions SELECT 'draft', agent_id, 'Draft', project_dir, 1, session_kind, NULL, created_at, updated_at FROM new_sessions WHERE id = 'deepchat-contract'"
        )
    assert [session.id for session in agent.get_sessions()] == ["deepchat-contract"]
    assert {session.id for session in agent.scan()} == {"deepchat-contract", "old"}
    assert agent.find_session_by_id("draft") is None
    old = agent.find_session_by_id("old")
    assert old is not None
    assert agent.get_session_facts(old).working_directory is None
    assert agent.get_session_head(old)["message_count"] == 0
    assert agent.get_session_head(old)["model"] is None


def test_source_identity_read_only_and_lightweight_facts(database, tmp_path, monkeypatch):
    agent = DeepChatAgent(database)
    before = database.read_bytes()
    session = agent.scan()[0]
    reader = DeepChatAgent(tmp_path / "unrelated.db")
    data = reader.get_session_data(session)
    assert data["messages"][0]["parts"][0]["text"] == "DeepChat prompt"
    assert data["messages"][1]["parts"][0]["text"] == "DeepChat answer"
    assert "Old prompt" not in json.dumps(data)
    assert data["stats"]["total_input_tokens"] == 10
    assert data["stats"]["total_output_tokens"] == 5
    assert database.read_bytes() == before
    with agent._connect_db(database) as conn, pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM deepchat_messages")
    with pytest.raises(FileNotFoundError):
        reader.get_session_data(replace(session, source_path=tmp_path / "missing.db"))
    assert not (tmp_path / "missing.db").exists()

    def reject_read(*args, **kwargs):
        pytest.fail("head and list must not read transcripts")

    monkeypatch.setattr(agent, "_connect_db", reject_read)
    assert agent.get_session_head(session)["message_count"] == 2
    assert agent.get_session_summary_fields(session)["model"] == "gpt-4.1"


@pytest.mark.parametrize("drop_tables", [False, True])
def test_content_fallback_and_compaction_collect_boundary(database, drop_tables):
    blocks = [
        {"type": "reasoning_content", "content": "Private reasoning"},
        {
            "type": "tool_call",
            "status": "error",
            "tool_call": {"id": "call-1", "name": "bash", "params": '{"command":"pytest"}', "response": "Tool failed"},
        },
        {"type": "plan", "content": "Internal plan", "status": "success"},
        {"type": "content", "content": "Visible answer"},
        {"type": "action", "content": "Permission required", "action_type": "tool_call_permission"},
        {"type": "image", "image_data": {"mimeType": "image/png", "data": "sample-image"}},
    ]
    with sqlite3.connect(database) as conn:
        for table in ("deepchat_user_messages", "deepchat_assistant_blocks"):
            conn.execute(f"DROP TABLE {table}" if drop_tables else f"DELETE FROM {table}")
        conn.execute("UPDATE deepchat_messages SET content = ? WHERE id = 'assistant-1'", (json.dumps(blocks),))
        conn.execute(
            "INSERT INTO deepchat_messages SELECT 'compaction', session_id, 3, role, ?, status, ?, created_at, updated_at FROM deepchat_messages WHERE id = 'assistant-1'",
            (
                json.dumps([{"type": "content", "content": "Compression marker"}]),
                json.dumps({"messageType": "compaction"}),
            ),
        )
    agent = DeepChatAgent(database)
    data = agent.get_session_data(agent.scan()[0])
    parts = data["messages"][1]["parts"]
    assert [part["type"] for part in parts] == ["reasoning", "tool", "plan", "text", "deepchat_action", "image"]
    assert parts[1]["state"] == {"status": "error", "input": {"command": "pytest"}, "output": "Tool failed"}
    assert parts[1]["callID"] == "call-1"
    assert data["messages"][2]["role"] == "compaction"
    events, truncated = extract_collect_events(data)
    assert [event.text for event in events] == ["Old prompt", "Visible answer"]
    assert not truncated


def test_structured_tools_attachments_and_order(database):
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO deepchat_assistant_blocks (message_id, block_index, block_type, status, tool_call_id, tool_name, tool_params, tool_response, extra_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "assistant-1",
                1,
                "tool_call",
                "success",
                "call-1",
                "read",
                '{"path":"test.py"}',
                "file contents",
                '{"timestamp":123}',
                999,
            ),
        )
        conn.execute(
            "INSERT INTO deepchat_user_message_files VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("user-1", 0, "file.txt", "/missing/file.txt", "text/plain", 10, "{}"),
        )
        conn.execute("INSERT INTO deepchat_user_message_links VALUES (?, ?, ?)", ("user-1", 0, "https://example.com"))
        conn.execute("UPDATE deepchat_messages SET created_at = 0 WHERE role = 'assistant'")
    agent = DeepChatAgent(database)
    data = agent.get_session_data(agent.scan()[0])
    assert [message["id"] for message in data["messages"]] == ["user-1", "assistant-1"]
    user, assistant = data["messages"]
    assert user["attachments"][0]["path"] == "/missing/file.txt"
    assert user["links"] == ["https://example.com"]
    assert assistant["parts"][1]["time_created"] == 123
    assert assistant["parts"][1]["state"]["output"] == "file contents"
    assert assistant["parts"][1]["state"]["status"] == "completed"


def test_wal_changes_refresh_transcript_and_search(database, tmp_path):
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        agent = DeepChatAgent(database)
        session = agent.scan()[0]
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, [session])
        assert index.search("answer")
        agent.get_cached_session_data(session)
        before = database.read_bytes()
        writer.execute("UPDATE deepchat_assistant_blocks SET text_content = 'Replacement text'")
        writer.commit()
        assert database.read_bytes() == before
        assert agent.get_cached_session_data(session)["messages"][1]["parts"][0]["text"] == "Replacement text"
        index.update(agent, [session])
        assert not index.search("answer")
        assert index.search("Replacement")
    finally:
        writer.close()


def test_unreadable_schema_and_raw_fail_explicitly(database, tmp_path):
    invalid = tmp_path / "encrypted.db"
    invalid.write_bytes(b"not a plaintext SQLite database" * 100)
    with pytest.raises(DiagnosticCapabilityError) as error:
        DeepChatAgent(invalid).scan()
    assert str(error.value) == expect(Keys.DIAG_DEEPCHAT_UNREADABLE)
    legacy = tmp_path / "chat.db"
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TABLE conversations (id TEXT)")
    with pytest.raises(DiagnosticCapabilityError) as error:
        DeepChatAgent(legacy).scan()
    assert str(error.value) == expect(Keys.DIAG_DEEPCHAT_SCHEMA)
    agent = DeepChatAgent(database)
    with pytest.raises(DiagnosticCapabilityError):
        agent.export_raw_session(agent.scan()[0], tmp_path / "raw")
    assert not (tmp_path / "raw").exists()


def test_missing_database_is_unavailable_and_bad_message_is_not_silently_dropped(database, tmp_path):
    missing = DeepChatAgent(tmp_path / "missing.db")
    assert not missing.discover_sessions().available
    assert missing.find_session_by_id("missing") is None
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM deepchat_assistant_blocks")
        conn.execute("UPDATE deepchat_messages SET content = 'invalid' WHERE role = 'assistant'")
    agent = DeepChatAgent(database)
    with pytest.raises(ValueError, match="assistant-1"):
        agent.get_session_data(agent.scan()[0])
