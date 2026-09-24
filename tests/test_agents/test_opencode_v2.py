from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from opencode_fixtures import create_opencode_v2_db, insert_message
import pytest

from agent_dump.agents.base import MessageCountCompleteness
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.collect_events import extract_collect_events
from agent_dump.paths import resolve_data_home
from agent_dump.query_semantics import extract_transcript_searchable_text
from agent_dump.search_index import SearchIndex


@pytest.fixture
def database(tmp_path):
    return create_opencode_v2_db(tmp_path / "session #?库.db", int(datetime.now(timezone.utc).timestamp() * 1000))


def reader(database):
    agent = OpenCodeAgent()
    agent.db_path = database
    return agent


def test_v2_discovery_facts_and_snapshot(database, monkeypatch):
    agent = reader(database)
    session = agent.discover_sessions().sessions[0]
    assert agent.find_session_by_id(session.id) == session
    assert agent.find_session_by_id("absent") is None
    facts = agent.get_session_facts(session)
    assert facts.model == "gpt-5"
    assert str(facts.working_directory) == "/workspace/opencode-v2"
    assert facts.provider_project == "proj_fixture"
    assert facts.message_count.value == 2
    assert session.source_path == database
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE session_v2 SET title = 'Updated title', directory = '/new', cost = 1.5")
    data = OpenCodeAgent().get_session_data(session)
    assert data["title"] == "Updated title"
    assert data["directory"] == "/new"
    assert data["stats"] == {
        "message_count": 2,
        "total_cost": 1.5,
        "total_input_tokens": 100,
        "total_output_tokens": 20,
    }

    def reject_read(*args, **kwargs):
        pytest.fail("head/list must not read the database")

    monkeypatch.setattr(agent, "_connect_db", reject_read)
    assert (
        agent.get_session_head(session)["message_count"] == agent.get_session_summary_fields(session)["message_count"]
    )
    assert agent.get_session_head(session)["subtargets"] == []
    assert (
        agent.get_session_facts(replace(session, metadata={})).message_count.completeness
        is MessageCountCompleteness.UNKNOWN
    )


def test_coexisting_schemas_prefer_v2_before_filtering(database, populated_db):
    with sqlite3.connect(populated_db) as old, sqlite3.connect(database) as conn:
        conn.executescript("\n".join(old.iterdump()))
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        conn.execute("UPDATE session SET time_created = ?, time_updated = ?", (now, now))
        conn.execute(
            "INSERT INTO session SELECT 'ses_v2', title, ?, ?, slug, directory, version, summary_files FROM session LIMIT 1",
            (now, now),
        )
        conn.execute("UPDATE session_v2 SET time_created = 1")
        old_id = conn.execute("SELECT id FROM session WHERE id != 'ses_v2'").fetchone()[0]
    agent = reader(database)
    assert [session.id for session in agent.get_sessions(days=7)] == [old_id]
    assert {session.id for session in agent.scan()} == {old_id, "ses_v2"}
    session = agent.find_session_by_id("ses_v2")
    assert session is not None
    assert session.title == "OpenCode V2 Contract"
    assert agent.get_session_data(session)["messages"][0]["parts"][0]["text"] == "OpenCode V2 prompt"
    old_session = agent.find_session_by_id(old_id)
    assert old_session is not None
    assert agent.get_session_data(old_session)["messages"][0]["parts"][0]["text"] == "Hello World"
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM session_v2")
    with pytest.raises(ValueError, match="missing"):
        agent.get_session_data(session)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE session_v2")
    with pytest.raises(ValueError, match="missing"):
        agent.get_session_data(session)


def test_message_order_roles_tools_metadata_and_collect(database):
    records = [
        ("system", {"text": "System instructions"}),
        ("skill", {"text": "Skill instructions", "name": "review"}),
        ("synthetic", {"text": "Automatic continuation"}),
        (
            "shell",
            {
                "shellID": "sh_1",
                "command": "pwd",
                "status": "exited",
                "exit": 0,
                "output": {"output": "Shell result", "truncated": True, "cursor": 10, "size": 20},
            },
        ),
        ("compaction", {"status": "completed", "summary": "Compressed history", "recent": "Recent history"}),
        ("agent-switched", {"agent": "plan"}),
        ("model-switched", {"model": {"id": "next-model", "providerID": "openai"}}),
        ("location-switched", {"location": {"directory": "/other"}}),
        ("idle", {"outcome": "succeeded"}),
        ("future-type", {"text": "private unknown metadata"}),
    ]
    attachment = {"data": "aGVsbG8=", "mime": "text/plain", "source": {"type": "uri", "uri": "file:///not-read"}}
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE session_message SET time_created = 0 WHERE type = 'assistant'")
        conn.execute(
            "UPDATE session_message SET data = ? WHERE type = 'user'",
            (json.dumps({"text": "OpenCode V2 prompt", "files": [attachment]}),),
        )
        for seq, (kind, data) in enumerate(records, 3):
            insert_message(conn, kind, data, seq=seq)
        conn.execute("CREATE TABLE session_inbox (payload TEXT)")
        conn.execute("INSERT INTO session_inbox VALUES ('not yet delivered')")
    agent = reader(database)
    session = agent.scan()[0]
    data = agent.get_session_data(session)
    user, assistant, *events = data["messages"]
    assert [user["id"], assistant["id"]] == ["msg_1", "msg_2"]
    assert user["metadata"]["files"] == [attachment]
    assert [part["type"] for part in assistant["parts"]] == ["reasoning", "text", "tool"]
    assert assistant["model"] == "gpt-5"
    assert assistant["provider"] == "openai"
    assert assistant["tokens"]["cache"]["read"] == 8
    assert assistant["cost"] == 0.25
    assert assistant["parts"][2]["state"]["output"][0]["text"] == "工具结果 ready"
    assert [message["role"] for message in events] == [
        "system",
        "system",
        "custom",
        "tool",
        "compaction",
        "custom",
        "custom",
        "custom",
        "custom",
        "unknown",
    ]
    assert data["stats"]["message_count"] == agent.get_session_head(session)["message_count"] == 12
    collected, truncated = extract_collect_events(data)
    assert [event.text for event in collected] == ["OpenCode V2 prompt", "OpenCode V2 answer"]
    assert not truncated
    corpus = extract_transcript_searchable_text(data)
    assert corpus is not None
    for text in (
        "Private reasoning",
        "工具结果 ready",
        "System instructions",
        "Automatic continuation",
        "Shell result",
    ):
        assert text in corpus
    assert "private unknown metadata" not in corpus
    assert "not-read" not in corpus


@pytest.mark.parametrize("status", ["streaming", "running", "completed", "error"])
def test_tool_states_and_unknown_content(database, status):
    state = {"status": status, "input": '{"command":' if status == "streaming" else {"command": "test"}}
    if status == "error":
        state["error"] = {"type": "ToolError", "message": "Permission denied"}
    if status == "completed":
        state["content"] = [{"type": "file", "uri": "file:///not-read.png", "mime": "image/png"}]
    with sqlite3.connect(database) as conn:
        insert_message(
            conn,
            "assistant",
            {
                "content": [
                    {"type": "tool", "id": "call_partial", "name": "bash", "state": state},
                    {"type": "future-part", "value": "preserved"},
                ]
            },
            seq=3,
        )
    agent = reader(database)
    data = agent.get_session_data(agent.scan()[0])
    message = data["messages"][-1]
    result = message["parts"][0]["state"]
    assert result["status"] == status
    assert result["input"] == state["input"]
    assert message["metadata"]["unmapped_content"] == [{"type": "future-part", "value": "preserved"}]
    if status == "error":
        assert "Permission denied" in (extract_transcript_searchable_text(data) or "")
    if status == "completed":
        assert result["output"] == state["content"]


@pytest.mark.parametrize("payload", ["{", "[]", '{"text":42}', '{"text":null}'])
def test_corrupt_message_fails_session_read(database, payload):
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE session_message SET data = ? WHERE type = 'user'", (payload,))
    agent = reader(database)
    with pytest.raises(ValueError, match="msg_1"):
        agent.get_session_data(agent.scan()[0])


@pytest.mark.parametrize("content", [None, [None], [{"type": "text", "text": 42}], [{"type": "tool", "state": []}]])
def test_corrupt_assistant_content_fails(database, content):
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE session_message SET data = ? WHERE type = 'assistant'", (json.dumps({"content": content}),)
        )
    agent = reader(database)
    with pytest.raises(ValueError, match="msg_2"):
        agent.get_session_data(agent.scan()[0])


def test_missing_message_table_and_unknown_schema(database):
    agent = reader(database)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE session_message")
    session = agent.scan()[0]
    assert agent.get_session_facts(session).message_count.completeness is MessageCountCompleteness.UNKNOWN
    with pytest.raises(sqlite3.OperationalError):
        agent.get_session_data(session)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE session_v2")
    with pytest.raises(sqlite3.OperationalError):
        agent.scan()


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_readonly_source_and_wal_cache_invalidation(database, tmp_path, journal_mode):
    agent = reader(database)
    writer = sqlite3.connect(database)
    try:
        writer.execute(f"PRAGMA journal_mode={journal_mode}")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        session = agent.scan()[0]
        before = hashlib.sha256(database.read_bytes()).digest()
        dump = list(writer.iterdump())
        data = agent.get_cached_session_data(session)
        assert data["messages"][0]["parts"][0]["text"] == "OpenCode V2 prompt"
        index = SearchIndex(tmp_path / "index.db")
        index.update(agent, [session])
        assert index.search("prompt")
        assert list(writer.iterdump()) == dump
        assert hashlib.sha256(database.read_bytes()).digest() == before
        writer.execute(
            "UPDATE session_message SET data = ? WHERE type = 'user'", (json.dumps({"text": "Replacement request"}),)
        )
        writer.commit()
        if journal_mode == "WAL":
            assert hashlib.sha256(database.read_bytes()).digest() == before
        assert agent.get_cached_session_data(session)["messages"][0]["parts"][0]["text"] == "Replacement request"
        index.update(agent, [session])
        assert not index.search("prompt")
        assert index.search("Replacement")
    finally:
        writer.close()


def test_source_path_is_authoritative(database, tmp_path):
    session = reader(database).scan()[0]
    other = create_opencode_v2_db(tmp_path / "other.db", 1)
    with sqlite3.connect(other) as conn:
        conn.execute("UPDATE session_message SET data = ? WHERE type = 'user'", (json.dumps({"text": "Other source"}),))
    agent = reader(other)
    assert agent.get_session_data(session)["messages"][0]["parts"][0]["text"] == "OpenCode V2 prompt"
    with pytest.raises(FileNotFoundError):
        agent.get_session_data(replace(session, source_path=tmp_path / "missing.db"))
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.parametrize("explicit", [None, "channel.db", "absolute", "missing", ":memory:"])
def test_database_selection(isolated_provider_home, monkeypatch, explicit):
    root = isolated_provider_home / ".local" / "share" / "opencode"
    default = create_opencode_v2_db(root / "opencode.db", 1)
    expected = default
    if explicit is not None:
        value = str(isolated_provider_home / "selected.db") if explicit == "absolute" else explicit
        monkeypatch.setenv("OPENCODE_DB", value)
        expected = root / value
        if explicit not in {"missing", ":memory:"}:
            create_opencode_v2_db(expected, 1)
    agent = OpenCodeAgent()
    discovery = agent.discover_sessions(days=None)
    if explicit in {"missing", ":memory:"}:
        assert not discovery.available
    else:
        assert discovery.sessions[0].source_path == expected


def test_windows_default_precedes_legacy_appdata(isolated_provider_home, monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setenv("LOCALAPPDATA", str(isolated_provider_home / "AppData"))
    monkeypatch.setattr(
        "agent_dump.agents.opencode.resolve_data_home",
        lambda *, is_windows=None: resolve_data_home(is_windows=True if is_windows is None else is_windows),
    )
    default = isolated_provider_home / ".local" / "share" / "opencode" / "opencode.db"
    legacy = create_opencode_v2_db(isolated_provider_home / "AppData" / "opencode" / "opencode.db", 1)
    assert OpenCodeAgent().scan()[0].source_path == legacy
    create_opencode_v2_db(default, 1)
    assert OpenCodeAgent().scan()[0].source_path == default
