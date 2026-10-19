"""Cursor discovery and transcript rules asserted on the Rust CLI."""

import json
import os
import sqlite3

from desktop_fixture import NOW
from test_cursor import cursor, put


def run_json(cli, *args):
    result = cli.run(*args, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)["data"]


def export(cli, uri):
    result = cli.run(uri, "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(next((cli.root / "exports/cursor").glob("*.json")).read_text())


def workspace(cli, name, folder, composers):
    directory = cli.source.parent.parent / "workspaceStorage" / name
    directory.mkdir(parents=True)
    (directory / "workspace.json").write_text(json.dumps({"folder": folder}))
    with sqlite3.connect(directory / "state.vscdb") as conn:
        conn.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        conn.execute(
            "INSERT INTO ItemTable VALUES ('composer.composerData', ?)",
            (json.dumps({"allComposers": [{"composerId": item} for item in composers]}),),
        )


def test_discovery_uses_composer_ids_titles_and_workspaces(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    put(cli, "bubbleId:parent:c-progress", {"type": 2, "kind": "progress", "text": "hidden"})
    put(cli, "composerData:no-id", {"name": "No id", "createdAt": NOW})
    put(cli, "bubbleId:no-id:a", {"type": 1, "text": "orphan"})
    put(cli, "composerData:empty", {"composerId": "empty", "name": "Empty", "createdAt": NOW})
    put(cli, "bubbleId:empty:a", {"type": 2, "thinking": {"text": "thought"}, "codeBlocks": [{"content": "x"}]})
    put(cli, "composerData:delegated", {"composerId": "delegated", "createdAt": NOW, "subagentInfos": [{"id": "s"}]})
    put(cli, "composerData:untitled", {"composerId": "untitled", "title": "  ", "createdAt": NOW})
    put(
        cli,
        "bubbleId:untitled:a",
        {"type": 1, "text": "<system-reminder>skip</system-reminder>\n\n  First   line  \nsecond"},
    )
    workspace(cli, "one", "file:///tmp/project%20one/./src/..", ["parent"])
    records = {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:cursor")}
    assert records.keys() == {"parent", "delegated", "untitled"}
    assert records["parent"]["title"] == "Cursor contract"
    assert records["parent"]["message_count"] == 2
    assert records["parent"]["working_directory"] == os.path.normpath("/tmp/project one")
    assert records["delegated"]["title"] == "Untitled Session"
    assert records["delegated"]["message_count"] == 0
    assert records["untitled"]["title"] == "First line"


def test_legacy_request_uri_finds_composer_session(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    legacy = run_json(cli, "cursor://request-parent", "--head")
    assert legacy == run_json(cli, "cursor://parent", "--head")
    assert legacy["uri"] == "cursor://parent"
    data = export(cli, "cursor://request-parent")
    assert data["id"] == "parent"
    assert [part["text"] for item in data["messages"] for part in item["parts"]] == ["prompt", "answer"]


def test_transcript_follows_bubble_rows_tools_and_subagents(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    with sqlite3.connect(cli.source) as conn:
        conn.execute("DELETE FROM cursorDiskKV WHERE key >= 'bubbleId:' AND key < 'bubbleId;'")
    put(
        cli,
        "composerData:parent",
        {
            "composerId": "parent",
            "name": "Cursor contract",
            "createdAt": NOW,
            "modelConfig": {"modelName": "composer-model"},
            "inputTokenCount": 99,
            "outputTokenCount": 77,
            "subagentInfos": [{"id": "sub", "nickname": "Reader"}],
        },
    )
    bubbles = [
        (
            "z-user",
            {
                "type": 1,
                "requestId": "request-parent",
                "text": "question",
                "codeBlocks": [{"content": "code"}],
                "usage": {"input_tokens": 50},
                "contextWindowStatusAtCreation": {"tokensUsed": 7},
                "timingInfo": {"clientRpcSendTime": NOW + 5000},
            },
        ),
        ("a-progress", {"type": 2, "eventType": "queue-operation", "text": "hidden"}),
        ("b-thinking", {"type": 2, "thinking": {"text": "thought"}, "codeBlocks": [{"content": "x"}]}),
        (
            "c-tool",
            {
                "type": 2,
                "text": "reading",
                "modelInfo": {"modelName": "bubble-model"},
                "timingInfo": {"clientRpcSendTime": NOW + 1000},
                "toolFormerData": {
                    "name": "read_file_v2",
                    "status": "failed",
                    "toolCallId": "call",
                    "params": '{"path":"a"}',
                    "result": '{"stderr":"boom"}',
                },
            },
        ),
        (
            "d-plan",
            {
                "type": 2,
                "toolFormerData": {"name": "create_plan", "status": "completed", "params": '{"plan":"  Steps  "}'},
            },
        ),
        ("e-plan", {"type": 2, "toolFormerData": {"name": "create_plan", "params": "{}"}}),
    ]
    for key, bubble in bubbles:
        put(cli, f"bubbleId:parent:{key}", bubble)
    with sqlite3.connect(cli.source) as conn:
        conn.execute("UPDATE cursorDiskKV SET value = CAST(value AS BLOB) WHERE key = 'bubbleId:parent:z-user'")
    put(
        cli,
        "bubble:sub",
        {
            "chatMessages": [
                {
                    "role": "assistant",
                    "text": "child",
                    "createdAt": NOW + 2000,
                    "actions": [
                        {
                            "type": "tool",
                            "tool": "read_file_v2",
                            "input": {"path": "b"},
                            "output": [{"text": "line"}],
                            "state": {"status": "completed"},
                        }
                    ],
                },
                {"role": "system", "text": "skipped"},
            ]
        },
    )
    data = export(cli, "cursor://parent")
    messages = data["messages"]
    assert [item["id"] for item in messages] == ["z-user", "c-tool", "d-plan", "e-plan", "subagent:sub:0"]
    assert messages[0]["parts"] == [{"type": "text", "text": "question", "time_created": NOW + 5000}]
    assert [item["model"] for item in messages[:4]] == ["composer-model", *["bubble-model"] * 3]
    text, tool = messages[1]["parts"]
    assert text["text"] == "reading" and messages[1]["mode"] == "tool"
    assert (tool["tool"], tool["callID"]) == ("read", "call")
    assert tool["state"] == {"status": "error", "input": {"path": "a"}, "output": {"stderr": "boom"}, "error": "boom"}
    plan = messages[2]["parts"][0]
    assert (plan["type"], plan["input"], plan["approval_status"]) == ("plan", "Steps", "success")
    assert messages[3]["parts"][0]["tool"] == "plan"
    assert messages[3]["parts"][0]["state"]["status"] == "running"
    child = messages[4]
    assert (child["role"], child["subagent_id"], child["nickname"]) == ("assistant", "sub", "Reader")
    assert child["parts"][1]["tool"] == "read"
    assert child["parts"][1]["state"]["output"] == [{"type": "text", "text": "line", "time_created": 0}]
    assert (data["stats"]["total_input_tokens"], data["stats"]["total_output_tokens"]) == (99, 77)
    assert data["stats"]["message_count"] == 5
