import json
import sqlite3

from desktop_fixture import desktop, exports, fails
import pytest


@pytest.mark.parametrize(
    "active,ids", [("empty", ["user", "answer"]), ("alternative", ["user", "alternative"]), ("root", []), (None, [])]
)
def test_active_branch_and_empty_leaf(tmp_path, monkeypatch, active, ids):
    cli, _ = desktop(tmp_path, monkeypatch, "cherry")
    with sqlite3.connect(cli.source) as conn:
        conn.execute("UPDATE topic SET active_node_id = ?", (active,))
    cli.parity("cherry://topic-contract", "--head", "--lang", "en")
    assert [m["id"] for m in exports(cli, "cherry", "topic-contract")["messages"]] == ids


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE message SET parent_id = 'empty' WHERE id = 'user'",
        "UPDATE message SET deleted_at = 1 WHERE id = 'user'",
        "UPDATE message SET topic_id = 'other' WHERE id = 'user'",
        "UPDATE topic SET active_node_id = 'absent'",
        "UPDATE message SET parent_id = 'answer' WHERE role = 'root'",
    ],
)
def test_broken_branch_preserves_other_sessions(tmp_path, monkeypatch, mutation):
    cli, _ = desktop(tmp_path, monkeypatch, "cherry")
    with sqlite3.connect(cli.source) as conn:
        conn.execute(mutation)
    before = cli.fixtures.source_manifest(cli.root)
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "--list", "-d", "36500", "-q", "provider:cherry", "--lang", "en")
        assert result.returncode == 0
        assert "cherry://session-contract" in result.stdout
        assert "cherry://topic-contract" not in result.stdout
        assert result.stderr
    fails(cli, "cherry://topic-contract")
    exports(cli, "cherry", "session-contract")
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("old_schema", [False, True])
def test_soft_delete_compatibility(tmp_path, monkeypatch, old_schema):
    cli, identity = desktop(tmp_path, monkeypatch, "cherry")
    with sqlite3.connect(cli.source) as conn:
        conn.execute("INSERT INTO topic SELECT 'deleted', name, active_node_id, created_at, updated_at, 1 FROM topic")
        if old_schema:
            conn.execute("ALTER TABLE agent_session DROP COLUMN deleted_at")
        else:
            conn.execute(
                "INSERT INTO agent_session SELECT 'deleted', name, workspace_id, created_at, updated_at, 1 FROM agent_session"
            )
    cli.parity("--list", "-d", "36500", "-q", "provider:cherry", "--lang", "en")
    exports(cli, "cherry", identity)


@pytest.mark.parametrize(
    "state",
    [
        "input-streaming",
        "input-available",
        "approval-requested",
        "approval-responded",
        "output-available",
        "output-error",
        "output-denied",
        "future",
    ],
)
def test_tool_parts_and_internal_references(tmp_path, monkeypatch, state):
    cli, identity = desktop(tmp_path, monkeypatch, "cherry")
    parts = [
        {"type": "reasoning", "text": "reason"},
        {
            "type": "tool-read",
            "toolCallId": "call",
            "state": state,
            "input": {"path": "/not-read"},
            "output": "result",
            "errorText": "denied",
            "approval": {"id": "approval"},
        },
        {"type": "dynamic-tool", "toolName": "write", "toolCallId": "write", "state": state},
        {"type": "data-code", "data": {"content": "print(1)"}},
        {"type": "data-translation", "data": {"content": "翻译"}},
        {"type": "data-error", "data": {"message": "problem"}},
        {"type": "file", "url": "file:///not-read"},
        {"type": "data-compact", "data": {"content": "Internal summary"}},
        {"type": "data-agent-task-event", "data": {"prompt": "Internal task"}},
    ]
    with sqlite3.connect(cli.source) as conn:
        conn.execute(
            "UPDATE agent_session_message SET data = ? WHERE role = 'assistant'", (json.dumps({"parts": parts}),)
        )
    data = exports(cli, "cherry", identity)
    assert data["messages"][1]["parts"][-1]["type"] == "cherry_data-agent-task-event"


@pytest.mark.parametrize(
    "snapshot,model",
    [
        (None, "openai::fallback"),
        ('{"model":"{\\"id\\":\\"nested\\",\\"provider\\":\\"p\\"}"}', None),
        ("{}", "plain-model"),
    ],
)
def test_model_snapshot_and_legacy_model_id(tmp_path, monkeypatch, snapshot, model):
    cli, identity = desktop(tmp_path, monkeypatch, "cherry")
    with sqlite3.connect(cli.source) as conn:
        conn.execute(
            "UPDATE agent_session_message SET message_snapshot = ?, model_id = ? WHERE role = 'assistant'",
            (snapshot, model),
        )
    cli.parity(f"cherry://{identity}", "--head", "--lang", "en")
    exports(cli, "cherry", identity)
