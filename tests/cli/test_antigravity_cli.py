"""Antigravity CLI conversation databases through the published CLI surface."""

import json
from pathlib import Path
import sqlite3

from cli_fixture import IDENTITY

STAMP = 1768478400


def encode(value):
    output = bytearray()
    while value >= 0x80:
        output.append(value & 0x7F | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def varint(number, value):
    return encode(number << 3) + encode(value)


def field(number, value):
    value = value.encode() if isinstance(value, str) else value
    return encode(number << 3 | 2) + encode(len(value)) + value


def metadata(created=None, call=None, usage=None):
    body = b""
    if created is not None:
        body += field(1, varint(1, created))
    if call is not None:
        body += field(4, call)
    if usage is not None:
        body += field(9, usage)
    return field(5, body)


def user(text, created=STAMP):
    return 14, field(19, field(2, text)) + metadata(created)


def assistant(text, created=STAMP, usage=None):
    return 15, field(20, field(1, text)) + metadata(created, usage=usage)


def create(cli, steps, *, identity=IDENTITY, conversations=None, summary=None, models=()):
    conversations = conversations or cli.root / "sources/antigravity-cli/conversations"
    conversations.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(conversations / f"{identity}.db")
    connection.executescript(
        "CREATE TABLE steps (idx INTEGER PRIMARY KEY, step_type INTEGER NOT NULL, status INTEGER NOT NULL,"
        " step_payload BLOB); CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB);"
    )
    connection.executemany(
        "INSERT INTO steps VALUES (?, ?, 3, ?)", [(index, kind, payload) for index, (kind, payload) in enumerate(steps)]
    )
    connection.executemany(
        "INSERT INTO gen_metadata (data) VALUES (?)",
        [(field(1, varint(3, model_id) + field(19, model)),) for model_id, model in models],
    )
    connection.commit()
    connection.close()
    if summary is not None:
        connection = sqlite3.connect(conversations.parent / "conversation_summaries.db")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS conversation_summaries (conversation_id TEXT PRIMARY KEY, title TEXT,"
            " workspace_uris TEXT, last_modified_time TEXT, parent_conversation_id TEXT)"
        )
        connection.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, '')",
            (identity, summary.get("title", ""), json.dumps(summary.get("workspaces", [])), summary.get("modified")),
        )
        connection.commit()
        connection.close()
    return conversations / f"{identity}.db"


def run_json(cli, *args):
    result = cli.run("rust", *args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def listed(cli):
    return {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:antigravity-cli")}


def test_list_head_and_export(cli):
    workspace = Path(cli.root / "workspace").resolve()
    usage = varint(1, 7) + varint(2, 10) + varint(3, 6) + varint(5, 2) + varint(9, 2) + field(11, "response")
    call = field(1, "call-1") + field(2, "read_file") + field(3, '{"path": "a.rs"}')
    create(
        cli,
        [
            user("<system-reminder>hidden</system-reminder>\nFix   the bug\nmore"),
            (15, metadata(STAMP + 1, usage=usage)),
            (132, metadata(call=call)),
            assistant("Done", STAMP + 2),
            (23, field(30, field(4, "Native title"))),
            (999, varint(100, 1)),
        ],
        summary={
            "title": "Summary title",
            "workspaces": [workspace.as_uri()],
            "modified": "2026-01-15 12:01:40.000000+00:00",
        },
        models=[(7, "gemini-3-pro")],
    )
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli)[IDENTITY]
    assert {key: record[key] for key in ("title", "created_at", "model", "message_count", "working_directory")} == {
        "title": "Native title",
        "created_at": "2026-01-15T12:00:00.000000+00:00",
        "model": "gemini-3-pro",
        "message_count": 3,
        "working_directory": str(workspace),
    }
    head = run_json(cli, f"antigravity-cli://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record

    result = cli.run("rust", f"antigravity-cli://{IDENTITY}", "--format", "json,md", "--output", "exports")
    assert result.returncode == 0, result.stderr
    exports = cli.root / "exports/antigravity-cli"
    assert "Fix   the bug" in (exports / f"{IDENTITY}.md").read_text()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before

    assert payload["stats"] == {
        "total_cost": 0,
        "total_input_tokens": 12,
        "total_output_tokens": 6,
        "message_count": 3,
        "total_tokens": 18,
    }
    prompt, tool, answer = payload["messages"]
    assert [part["text"] for part in prompt["parts"]] == ["Fix   the bug\nmore"]
    assert (tool["role"], tool["model"], tool["inferred_time"]) == ("assistant", "gemini-3-pro", True)
    assert tool["time_created"] == (STAMP + 100) * 1000
    assert tool["tokens"] == {"input": 12, "output": 4, "reasoning": 2, "cache": {"read": 2, "write": 0}}
    (part,) = tool["parts"]
    assert (part["tool"], part["callID"], part["state"]["status"], part["state"]["input"]) == (
        "read_file",
        "call-1",
        "unknown",
        {"path": "a.rs"},
    )
    assert (answer["agent"], answer["parts"][0]["text"], "inferred_time" in answer) == (
        "antigravity-cli",
        "Done",
        False,
    )


def test_default_root_override_and_empty_databases(cli):
    home = Path(cli.environment["HOME"])
    create(
        cli,
        [user("Default prompt")],
        identity="default",
        conversations=home / ".gemini/antigravity-cli/conversations",
        summary={"title": "Default title"},
    )
    create(cli, [user("Override prompt")], identity="override")
    create(cli, [], identity="empty")

    assert {key: item["title"] for key, item in listed(cli).items()} == {"override": "Override prompt"}
    missing = cli.run("rust", "antigravity-cli://empty", "--head")
    assert missing.returncode == 1

    del cli.environment["AGY_CONVERSATIONS_DIR"]
    assert {key: item["title"] for key, item in listed(cli).items()} == {"default": "Default title"}
