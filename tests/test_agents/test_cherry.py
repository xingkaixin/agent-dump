from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from cherry_fixtures import create_cherry_db
from locale_helpers import expect
import pytest

from agent_dump.agents.cherry import CherryStudioAgent
from agent_dump.collect_events import extract_collect_events
from agent_dump.diagnostics import DiagnosticCapabilityError
from agent_dump.i18n import Keys
from agent_dump.search_index import SearchIndex


@pytest.fixture
def database(tmp_path):
    return create_cherry_db(
        tmp_path / "Data" / "cherrystudio.sqlite", int(datetime.now(timezone.utc).timestamp() * 1000)
    )


@pytest.mark.parametrize(
    ("platform", "env", "relative"),
    [
        ("darwin", {}, "Library/Application Support/CherryStudio"),
        ("win32", {}, "AppData/Roaming/CherryStudio"),
        ("linux", {}, ".config/CherryStudio"),
        ("win32", {"APPDATA": "roaming"}, "roaming/CherryStudio"),
        ("linux", {"XDG_CONFIG_HOME": "config"}, "config/CherryStudio"),
        ("darwin", {"CHERRY_STUDIO_USER_DATA_DIR": "custom"}, "custom"),
    ],
)
def test_default_and_override_paths(tmp_path, monkeypatch, platform, env, relative):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("agent_dump.agents.cherry_storage.sys.platform", platform)
    for name in ("APPDATA", "XDG_CONFIG_HOME", "CHERRY_STUDIO_USER_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    for name, path in env.items():
        monkeypatch.setenv(name, str(tmp_path / path))
    assert CherryStudioAgent().get_search_roots()[0].path == tmp_path / relative / "Data" / "cherrystudio.sqlite"


def test_boot_config_relocation_and_override(database, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CHERRY_STUDIO_USER_DATA_DIR")
    boot = tmp_path / ".cherrystudio" / "boot-config.json"
    boot.parent.mkdir()
    boot.write_text(json.dumps({"app.user_data_path": {"/bin/cherry": str(tmp_path), "/bin/other": str(tmp_path)}}))
    agent = CherryStudioAgent()
    assert agent.get_search_roots()[0].path == database
    assert len(agent.get_search_roots()) == 2
    assert len(agent.scan()) == 2
    monkeypatch.setenv("CHERRY_STUDIO_USER_DATA_DIR", str(tmp_path / "absent"))
    assert not CherryStudioAgent().is_available()


def test_both_session_kinds_have_distinct_identity_and_branch_facts(database):
    before = database.read_bytes()
    agent = CherryStudioAgent(database)
    sessions = {session.id: session for session in agent.scan()}
    assert set(sessions) == {"topic-contract", "session-contract"}
    for session in sessions.values():
        facts = agent.get_session_facts(session)
        assert facts.message_count.exact_value == 2
        assert facts.model == "gpt-4.1"
        assert agent.get_session_head(session)["message_count"] == 2
        data = agent.get_session_data(session)
        assert data["stats"]["message_count"] == 2
        assert [message["parts"][0]["text"] for message in data["messages"]] == ["Cherry prompt", "Cherry answer"]
    assert agent.get_session_facts(sessions["topic-contract"]).working_directory is None
    assert agent.get_session_facts(sessions["session-contract"]).working_directory == Path("/workspace/cherry-contract")
    assert database.read_bytes() == before
    with agent._connect_db(database) as conn, pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM topic")


def test_window_soft_deletes_and_direct_lookup(database):
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE topic SET created_at = 1")
        conn.execute(
            "INSERT INTO topic SELECT 'deleted', 'Deleted', active_node_id, created_at, updated_at, 1 FROM topic"
        )
        conn.execute(
            "INSERT INTO agent_session SELECT 'deleted', name, workspace_id, created_at, updated_at, 1 FROM agent_session"
        )
    agent = CherryStudioAgent(database)
    assert [session.id for session in agent.get_sessions()] == ["session-contract"]
    assert len(agent.scan()) == 2
    assert agent.find_session_by_id("topic-contract") is not None
    for session_id in ("contract", "topic-deleted", "session-deleted", "topic-' OR 1=1--"):
        assert agent.find_session_by_id(session_id) is None


def test_agent_sessions_before_soft_delete_migration_remain_readable(database, tmp_path):
    with sqlite3.connect(database) as conn:
        conn.execute("ALTER TABLE agent_session DROP COLUMN deleted_at")
    before = database.read_bytes()
    agent = CherryStudioAgent(database)
    discovery = agent.discover_sessions(None)
    assert discovery.available and discovery.complete
    assert {session.id for session in discovery.sessions} == {"topic-contract", "session-contract"}
    for listed in discovery.sessions:
        session = agent.find_session_by_id(listed.id)
        assert session is not None
        assert agent.get_session_head(session)["message_count"] == 2
        exported = json.loads(agent.export_session(session, tmp_path / "exports").read_text())
        assert exported["stats"]["message_count"] == 2
        assert [message["parts"][0]["text"] for message in exported["messages"]] == ["Cherry prompt", "Cherry answer"]
    assert database.read_bytes() == before


def test_fresh_reader_uses_session_source_and_rejects_missing_records(database, tmp_path):
    session = CherryStudioAgent(database).find_session_by_id("session-contract")
    assert session is not None
    reader = CherryStudioAgent(tmp_path / "unrelated.db")
    data = reader.get_session_data(session)
    assert data["stats"]["total_input_tokens"] == 12
    assert data["stats"]["total_output_tokens"] == 7
    with pytest.raises(FileNotFoundError):
        reader.get_session_data(replace(session, source_path=tmp_path / "missing.db"))
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM agent_session")
    with pytest.raises(FileNotFoundError):
        reader.get_session_data(session)
    assert not (tmp_path / "missing.db").exists()


def test_parts_preserve_tools_and_references_without_collecting_control_text(database, tmp_path):
    parts = [
        {"type": "reasoning", "text": "Reasoned answer"},
        {
            "type": "tool-read",
            "toolCallId": "read-1",
            "state": "output-available",
            "input": {"path": "/a"},
            "output": "Tool output",
        },
        {
            "type": "dynamic-tool",
            "toolName": "write",
            "toolCallId": "write-1",
            "state": "output-error",
            "errorText": "Denied",
        },
        {"type": "tool-exec", "toolCallId": "exec-1", "state": "approval-requested", "approval": {"id": "approve-1"}},
        {"type": "data-code", "data": {"content": "print(1)", "language": "python"}},
        {"type": "data-translation", "data": {"content": "翻译结果"}},
        {"type": "text", "text": "Visible answer"},
        {"type": "file", "url": "file:///missing/file.txt", "mediaType": "text/plain"},
        {"type": "data-compact", "data": {"content": "Internal summary", "compactedContent": "Internal summary"}},
        {"type": "data-agent-task-event", "data": {"prompt": "Internal task"}},
        {"type": "data-clear", "data": {}},
    ]
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE agent_session_message SET data = ? WHERE role = 'assistant'", (json.dumps({"parts": parts}),)
        )
        conn.execute("UPDATE agent_session_message SET model_id = NULL WHERE role = 'assistant'")
    agent = CherryStudioAgent(database)
    session = agent.find_session_by_id("session-contract")
    assert session is not None
    data = agent.get_session_data(session)
    message = data["messages"][1]
    assert message["model"] == "gpt-4.1"
    assert message["provider"] == "openai"
    assert message["tokens"]["cache"]["read"] == 3
    decoded = message["parts"]
    assert decoded[1]["state"]["output"] == "Tool output"
    assert [part["state"]["status"] for part in decoded[1:4]] == ["completed", "error", "pending"]
    assert decoded[2]["state"]["error"] == "Denied"
    assert decoded[7]["data"]["url"] == "file:///missing/file.txt"
    events, truncated = extract_collect_events(data)
    assert not truncated
    text = "\n".join(event.text for event in events)
    assert "Visible answer" in text
    assert "Internal summary" not in text
    assert "Internal task" not in text
    index = SearchIndex(tmp_path / "index.db")
    index.update(agent, [session])
    assert index.search("Reasoned")
    assert index.search("Tool output")
    assert not index.search("Internal")


def test_wal_branch_switch_refreshes_cached_data_and_search(database, tmp_path):
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        agent = CherryStudioAgent(database)
        session = agent.find_session_by_id("topic-contract")
        assert session is not None
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, [session])
        assert index.search("answer")
        assert not index.search("Unselected")
        agent.get_cached_session_data(session)
        before = database.read_bytes()
        writer.execute("UPDATE topic SET active_node_id = 'alternative'")
        writer.commit()
        assert database.read_bytes() == before
        assert agent.get_cached_session_data(session)["messages"][1]["parts"][0]["text"] == "Unselected reply"
        index.update(agent, [session])
        assert not index.search("answer")
        assert index.search("Unselected")
    finally:
        writer.close()


@pytest.mark.parametrize("damage", ["cycle", "deleted", "cross-topic", "missing"])
def test_broken_branch_is_reported_without_losing_agent_sessions(database, damage):
    with sqlite3.connect(database) as conn:
        if damage == "cycle":
            conn.execute("UPDATE message SET parent_id = 'empty' WHERE id = 'user'")
        elif damage == "deleted":
            conn.execute("UPDATE message SET deleted_at = 1 WHERE id = 'user'")
        elif damage == "cross-topic":
            conn.execute("UPDATE message SET topic_id = 'another' WHERE id = 'user'")
        else:
            conn.execute("UPDATE topic SET active_node_id = 'missing'")
    agent = CherryStudioAgent(database)
    diagnostics = []
    with agent.diagnostic_context(diagnostics.append):
        discovery = agent.discover_sessions(None)
    assert discovery.available and not discovery.complete
    assert [session.id for session in discovery.sessions] == ["session-contract"]
    assert len(diagnostics) == 1
    with pytest.raises(ValueError, match="branch"):
        agent.find_session_by_id("topic-contract")


def test_missing_schema_bad_json_and_raw_fail_explicitly(database, tmp_path):
    missing = CherryStudioAgent(tmp_path / "missing.db")
    assert not missing.discover_sessions().available
    assert missing.find_session_by_id("session-contract") is None
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TABLE old_sessions (id TEXT)")
    with pytest.raises(DiagnosticCapabilityError) as error:
        CherryStudioAgent(legacy).scan()
    assert str(error.value) == expect(Keys.DIAG_CHERRY_SCHEMA)
    agent = CherryStudioAgent(database)
    session = agent.find_session_by_id("session-contract")
    assert session is not None
    with pytest.raises(DiagnosticCapabilityError):
        agent.export_raw_session(session, tmp_path / "raw")
    assert not (tmp_path / "raw").exists()
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE agent_session_message SET data = 'invalid' WHERE role = 'assistant'")
    with pytest.raises(ValueError, match="b-assistant"):
        agent.get_session_data(session)
