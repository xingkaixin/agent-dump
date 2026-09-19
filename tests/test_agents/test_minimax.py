from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3

from minimax_fixtures import create_minimax_db, insert_message
import pytest

from agent_dump.agents.base import MessageCountCompleteness
from agent_dump.agents.minimax import MiniMaxAgent
from agent_dump.collect_events import extract_collect_events
from agent_dump.diagnostics import DiagnosticError
from agent_dump.i18n import Keys


@pytest.fixture
def database(tmp_path):
    return create_minimax_db(
        tmp_path / "v2" / "sqlite" / "runtime-state.sqlite", int(datetime.now(timezone.utc).timestamp() * 1000)
    )


@pytest.mark.parametrize(
    ("primary", "legacy", "relative"),
    [(None, None, ".minimax"), ("   ", "  ", ".minimax"), (" selected ", "other", "selected"), (" ", " old ", "old")],
)
def test_search_root_precedence(isolated_provider_home, monkeypatch, primary, legacy, relative):
    for key, value in (("MINIMAX_DATA_DIR", primary), ("MAVIS_DATA_DIR", legacy)):
        if value is not None:
            monkeypatch.setenv(key, value if value.isspace() else f" {isolated_provider_home / value.strip()} ")
    (root,) = MiniMaxAgent().get_search_roots()
    assert root.path == isolated_provider_home / relative / "v2" / "sqlite" / "runtime-state.sqlite"


def test_explicit_source_does_not_fall_back(isolated_provider_home, monkeypatch, tmp_path):
    default = create_minimax_db(isolated_provider_home / ".minimax" / "v2" / "sqlite" / "runtime-state.sqlite", 1)
    monkeypatch.setenv("MINIMAX_DATA_DIR", str(tmp_path / "missing"))
    assert not MiniMaxAgent().discover_sessions().available
    assert not MiniMaxAgent(tmp_path / "missing.sqlite").discover_sessions().available
    assert MiniMaxAgent(default).scan()[0].id == "minimax-contract"


def test_discovery_scope_and_time_window(database):
    with sqlite3.connect(database) as conn:
        now = conn.execute("SELECT created_at_ms FROM local_runtime_sessions").fetchone()[0]
        for session_id, runtime, visibility, kind, archived, created in [
            ("archived", "pi-agent", "visible", "conversation", 1, now),
            ("child", "pi-agent", "visible", "task", 0, now),
            ("unknown", "pi-agent", "visible", "unknown", 0, now),
            ("hidden", "pi-agent", "hidden", "conversation", 0, now),
            ("peek", "pi-agent", "visible", "peek", 0, now),
            ("channel", "pi-agent", "visible", "channel", 0, now),
            ("cron", "pi-agent", "visible", "cron", 0, now),
            ("old-runtime", "opencode", "visible", "conversation", 0, now),
            ("old", "pi-agent", "visible", "conversation", 0, 1),
        ]:
            conn.execute(
                """INSERT INTO local_runtime_sessions
                   (session_id, runtime, visibility, session_kind, archived, parent_session_id, created_at_ms, updated_at_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, runtime, visibility, kind, archived, "minimax-contract", created, now),
            )
    agent = MiniMaxAgent(database)
    discovery = agent.discover_sessions()
    assert discovery.complete
    assert {session.id for session in discovery.sessions} == {"minimax-contract", "archived", "child", "unknown"}
    child = agent.find_session_by_id("child")
    assert child is not None
    assert child.metadata["parent_session_id"] == "minimax-contract"
    assert agent.get_session_data(child)["messages"] == []
    assert agent.get_session_head(child)["message_count"] == 0
    assert agent.find_session_by_id("hidden") is None
    assert agent.find_session_by_id("' OR 1=1 --") is None
    assert "old" in {session.id for session in agent.scan()}


def test_metadata_only_discovery_and_unknown_facts(database, monkeypatch):
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE local_runtime_message_rows SET data_json = 'not-json'")
    agent = MiniMaxAgent(database)
    session = agent.scan()[0]
    facts = agent.get_session_facts(session)
    assert facts.message_count.exact_value == 2
    assert facts.model == "minimax/MiniMax-M3"
    assert facts.working_directory == Path("/workspace/minimax-contract")
    with pytest.raises(ValueError):
        agent.get_session_data(session)
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE local_runtime_sessions SET title = '', workspace_dir = NULL, extra_data_json = '{}', created_at_ms = NULL"
        )
    unknown = agent.scan()[0]
    assert unknown.title == unknown.id
    assert unknown.created_at == unknown.updated_at
    assert agent.get_session_facts(unknown).model is None
    assert agent.get_session_facts(unknown).working_directory is None

    def reject_read(*args, **kwargs):
        pytest.fail("head must project discovered facts without I/O")

    monkeypatch.setattr(agent, "_connect_db", reject_read)
    assert agent.get_session_head(session)["message_count"] == 2
    assert agent.get_session_summary_fields(unknown)["model"] is None
    manual = replace(session, metadata={})
    assert agent.get_session_facts(manual).message_count.completeness is MessageCountCompleteness.UNKNOWN


def test_message_order_tools_tokens_and_collect(database):
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE local_runtime_message_rows SET created_at_ms = 1 WHERE msg_id = 'assistant-1'")
        for index, data in enumerate(
            [
                {"kind": "compaction_start"},
                {"kind": "compaction"},
                {"kind": "compaction_failed"},
                {"kind": "review_result"},
                {"msg_type": 3},
                {"msg_type": 99},
                {"role": "user", "msg_content": "<permission-response>yes</permission-response>"},
            ]
        ):
            insert_message(
                conn, {"msg_id": f"event-{index}", "role": "assistant", "msg_content": "Internal event", **data}
            )
    agent = MiniMaxAgent(database)
    session = agent.scan()[0]
    data = agent.get_session_data(session)
    user, assistant, *events = data["messages"]
    assert [user["id"], assistant["id"]] == ["user-1", "assistant-1"]
    assert user["attachments"][0]["path"] == "/not-read/spec.txt"
    assert [part["type"] for part in assistant["parts"]] == ["reasoning", "text", "tool"]
    tool = assistant["parts"][2]
    assert tool["state"]["status"] == "completed"
    assert tool["state"]["input"] == {"command": "printf ready"}
    assert tool["state"]["output"]["content"][0]["text"] == "工具完成\nready"
    assert assistant["tokens"] == {"input": 30, "output": 10, "total": 45, "cache": {"read": 5}}
    assert user["tokens"] == {}
    assert [event["role"] for event in events] == [
        "compaction",
        "compaction",
        "compaction",
        "custom",
        "system",
        "unknown",
        "custom",
    ]
    assert agent.get_session_head(session)["message_count"] == data["stats"]["message_count"] == 9
    collected, truncated = extract_collect_events(data)
    assert [event.text for event in collected] == ["MiniMax prompt", "MiniMax answer"]
    assert not truncated


@pytest.mark.parametrize(
    ("status", "expected"),
    [(1, "running"), (2, "completed"), (3, "error"), (4, "pending"), (5, "pending"), (99, "unknown")],
)
def test_tool_lifecycle_and_partial_arguments(database, status, expected):
    with sqlite3.connect(database) as conn:
        insert_message(
            conn,
            {
                "msg_id": "partial",
                "role": "assistant",
                "tool_calls": [
                    {
                        "tool_name": "bash",
                        "tool_call_id": "tool-2",
                        "tool_call_status": status,
                        "tool_call_args_delta": '{"command":',
                        "tool_call_result_data": "unfinished output",
                    }
                ],
            },
        )
    agent = MiniMaxAgent(database)
    state = agent.get_session_data(agent.scan()[0])["messages"][-1]["parts"][0]["state"]
    assert state["status"] == expected
    assert state["input"] == '{"command":'
    assert state["output"] == "unfinished output"


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "[]",
        '{"msg_id":"wrong"}',
        '{"msg_id":"user-1","role":"user","msg_content":42}',
        '{"msg_id":"user-1","role":"user","tool_calls":[null]}',
    ],
)
def test_corrupt_display_messages_fail_without_fallback(database, payload):
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE local_runtime_message_rows SET data_json = ? WHERE msg_id = 'user-1'", (payload,))
    agent = MiniMaxAgent(database)
    with pytest.raises(ValueError):
        agent.get_session_data(agent.scan()[0])


@pytest.mark.parametrize("failure", ["version", "metadata", "migration"])
def test_partial_discovery_keeps_valid_sessions(database, failure):
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO local_runtime_sessions (session_id, created_at_ms, updated_at_ms) VALUES ('broken', 1, 2)"
        )
        if failure == "version":
            conn.execute("UPDATE local_runtime_sessions SET columnar_version = 4 WHERE session_id = 'broken'")
        elif failure == "metadata":
            conn.execute("UPDATE local_runtime_sessions SET extra_data_json = '[' WHERE session_id = 'broken'")
        else:
            conn.execute("INSERT INTO local_runtime_messages VALUES ('broken', '[{\"msg_id\":\"legacy\"}]')")
    diagnostics = []
    agent = MiniMaxAgent(database)
    with agent.diagnostic_context(diagnostics.append):
        discovery = agent.discover_sessions(days=None)
    assert not discovery.complete
    assert [session.id for session in discovery.sessions] == ["minimax-contract"]
    assert diagnostics[0].message_key == Keys.WARN_MINIMAX_SESSION_READ_FAILED
    with pytest.raises(ValueError):
        agent.find_session_by_id("broken")


def test_migration_marker_prevents_stale_blob_resurrection(database):
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO local_runtime_messages VALUES ('minimax-contract', '[{\"msg_id\":\"stale\"}]')")
    agent = MiniMaxAgent(database)
    assert agent.discover_sessions(days=None).complete
    assert len(agent.get_session_data(agent.scan()[0])["messages"]) == 2


def test_readonly_wal_cache_and_source_identity(database, tmp_path):
    agent = MiniMaxAgent(database)
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        session = agent.scan()[0]
        initial = agent.get_cached_session_data(session)
        insert_message(writer, {"msg_id": "later", "role": "assistant", "msg_content": "New WAL answer"})
        writer.commit()
        paths = (database, Path(f"{database}-wal"))
        before = [hashlib.sha256(path.read_bytes()).digest() for path in paths]
        assert len(initial["messages"]) == 2
        assert len(agent.get_cached_session_data(session)["messages"]) == 3
        agent.export_session(session, tmp_path / "exports")
        assert [hashlib.sha256(path.read_bytes()).digest() for path in paths] == before
        with agent._connect_db(database) as conn, pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM local_runtime_message_rows")
        other = create_minimax_db(tmp_path / "other.sqlite", 1)
        reader = MiniMaxAgent(other)
        assert len(reader.get_session_data(session)["messages"]) == 3
        with pytest.raises(FileNotFoundError):
            reader.get_session_data(replace(session, source_path=tmp_path / "missing.sqlite"))
        assert not (tmp_path / "missing.sqlite").exists()
    finally:
        writer.close()


@pytest.mark.parametrize("break_schema", ["table", "column"])
def test_unsupported_schema_is_not_an_empty_provider(database, break_schema):
    with sqlite3.connect(database) as conn:
        conn.execute(
            "DROP TABLE local_runtime_messages"
            if break_schema == "table"
            else "ALTER TABLE local_runtime_message_rows RENAME COLUMN data_json TO unsupported"
        )
    with pytest.raises(DiagnosticError):
        MiniMaxAgent(database).discover_sessions()


def test_missing_empty_and_deleted_sources(database, tmp_path):
    missing = MiniMaxAgent(tmp_path / "not-created.sqlite")
    assert not missing.discover_sessions().available
    agent = MiniMaxAgent(database)
    session = agent.scan()[0]
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM local_runtime_sessions")
    assert agent.discover_sessions().available
    assert agent.scan() == []
    with pytest.raises(FileNotFoundError):
        agent.get_session_data(session)
