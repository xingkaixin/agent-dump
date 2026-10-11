"""Cursor discovery and subagent boundaries asserted on the Rust CLI."""

import json
import sqlite3

from desktop_fixture import NOW
from test_cursor import cursor, put


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


def test_long_subagent_chain_keeps_every_completion(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    parent = "parent"
    for index in range(128):
        child = f"child-{index}"
        put(
            cli,
            f"composerData:{child}",
            {"name": child, "createdAt": NOW, "subagentInfo": {"parentComposerId": parent}},
        )
        put(
            cli,
            f"bubbleId:{parent}:c-task",
            {"type": 2, "toolFormerData": {"name": "agent", "additionalData": {"subagentComposerId": child}}},
        )
        put(cli, f"bubbleId:{child}:a-answer", {"type": 2, "text": f"Completed {index}"})
        parent = child
    result = cli.run("rust", "cursor://request-parent", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    data = json.loads(next((cli.root / "exports" / "cursor").glob("*.json")).read_text())
    output = next(item for item in data["messages"] if item["id"].endswith(":subagent-output"))
    assert [part["text"] for part in output["parts"]] == [f"Completed {index}" for index in range(128)]
