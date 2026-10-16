"""Cursor discovery and transcript rules asserted on the Rust CLI."""

import json
import sqlite3

from desktop_fixture import NOW
from test_cursor import cursor, put


def export(cli, uri):
    result = cli.run("rust", uri, "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(next((cli.root / "exports/cursor").glob("*.json")).read_text())


def test_discovery_reads_metadata_beyond_one_batch(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    requests = [f"request-{index:03d}" for index in range(103)]
    with sqlite3.connect(cli.source) as conn:
        for index, request in enumerate(requests):
            identity = f"composer-{index:03d}"
            conn.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (f"composerData:{identity}", json.dumps({"name": identity, "createdAt": NOW})),
            )
            conn.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (
                    f"bubbleId:{identity}:a",
                    json.dumps({"type": 1, "requestId": request, "modelInfo": {"modelName": "batch"}}),
                ),
            )
    result = cli.run("rust", "--list", "--json", "-d", "36500", "-q", "provider:cursor")
    assert result.returncode == 0, result.stderr
    records = {item["id"]: item for item in json.loads(result.stdout)["data"]}
    assert records.keys() == {"request-parent", *requests}
    assert all(records[request]["model"] == "batch" for request in requests)
    assert all(records[request]["message_count"] == 1 for request in requests)


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
    data = export(cli, "cursor://request-parent")
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
