"""Gemini CLI chats through the published CLI surface."""

import json
from pathlib import Path

from cli_fixture import IDENTITY, write_jsonl

START = "2026-01-15T12:00:00.000Z"


def create(cli, records, *, project="project", name=f"session-2026-01-15T12-00-{IDENTITY[:8]}.jsonl", root=None):
    chats = (root or cli.root / "sources/gemini-cli") / ".gemini/tmp" / project / "chats"
    return write_jsonl(chats / name, records)


def header(identity=IDENTITY, **fields):
    return {"sessionId": identity, "projectHash": "hash", "startTime": START, "lastUpdated": START, **fields}


def entry(identity, kind, content, **fields):
    return {"id": identity, "timestamp": START, "type": kind, "content": content, **fields}


def run_json(cli, *args):
    result = cli.run("rust", *args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def listed(cli):
    return {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:gemini-cli")}


def call(identity, name, args, status, result):
    return {"id": identity, "name": name, "args": args, "status": status, "result": result}


def response(identity, name, body):
    return {"functionResponse": {"id": identity, "name": name, "response": body}}


STREAM = [
    header(),
    entry(
        "u1",
        "user",
        [{"text": "Explain @a.rs\n--- Content from referenced files ---"}],
        displayContent=[{"text": "<system-reminder>hidden</system-reminder>\nExplain   @a.rs"}],
    ),
    entry(
        "g1",
        "gemini",
        "",
        model="gemini-2.5-pro",
        thoughts=[{"subject": "Reading", "description": "Open the file."}],
        tokens={"input": 100, "output": 5, "cached": 40, "thoughts": 3, "tool": 2},
        toolCalls=[
            call("read", "read_file", {"path": "a.rs"}, "success", [response("read", "read_file", {"output": "fn"})]),
            call("shell", "run_shell_command", {"command": "false"}, "error", None),
        ],
    ),
    {
        "$patch": {
            "updates": [
                {
                    "id": "g1",
                    "toolCalls": [
                        {"id": "shell", "result": [response("shell", "run_shell_command", {"error": "exit 1"})]}
                    ],
                }
            ]
        }
    },
    entry("u2", "user", [response("read", "read_file", {"output": "fn"})]),
    entry("g2", "gemini", [{"text": "Plan", "thought": True}, {"text": "Done."}], tokens={"input": 10, "output": 2}),
    entry("g3", "gemini", "Dropped by rewind"),
    {"$rewindTo": "g3"},
    {"$set": {"summary": "Explain the entry point", "lastUpdated": "2026-01-15T12:05:00.000Z"}},
]


def test_list_head_and_export(cli):
    source = create(cli, STREAM)
    (source.parents[1] / ".project_root").write_text("/workspace/gemini\n")
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli)[IDENTITY]
    assert {
        key: record[key] for key in ("title", "created_at", "updated_at", "model", "message_count", "working_directory")
    } == {
        "title": "Explain the entry point",
        "created_at": "2026-01-15T12:00:00.000000+00:00",
        "updated_at": "2026-01-15T12:05:00.000000+00:00",
        "model": "gemini-2.5-pro",
        "message_count": 3,
        "working_directory": "/workspace/gemini",
    }
    head = run_json(cli, f"gemini-cli://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record

    result = cli.run("rust", f"gemini-cli://{IDENTITY}", "--format", "json,md,raw", "--output", "exports")
    assert result.returncode == 0, result.stderr
    exports = cli.root / "exports/gemini-cli"
    assert (exports / f"{IDENTITY}.raw.jsonl").read_bytes() == source.read_bytes()
    assert "Explain   @a.rs" in (exports / f"{IDENTITY}.md").read_text()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before

    assert payload["stats"] == {
        "total_cost": 0,
        "total_input_tokens": 112,
        "total_output_tokens": 10,
        "message_count": 3,
        "total_tokens": 122,
    }
    user, first, second = payload["messages"]
    assert [part["text"] for part in user["parts"]] == ["Explain   @a.rs"]
    assert (first["agent"], first["model"]) == ("gemini-cli", "gemini-2.5-pro")
    assert first["tokens"] == {"input": 102, "output": 5, "reasoning": 3, "cache": {"read": 40}}
    reasoning, read, shell = first["parts"]
    assert (reasoning["type"], reasoning["text"]) == ("reasoning", "**Reading** Open the file.")
    assert (read["tool"], read["callID"], read["state"]) == (
        "read_file",
        "read",
        {"status": "completed", "input": {"path": "a.rs"}, "output": "fn", "error": None},
    )
    assert (shell["state"]["status"], shell["state"]["output"], shell["state"]["error"]) == ("error", None, "exit 1")
    assert [(part["type"], part["text"]) for part in second["parts"]] == [("reasoning", "Plan"), ("text", "Done.")]


def test_discovery_reads_chats_and_subagents_only(cli):
    prompt = [entry("u", "user", "<session_context>cwd</session_context>"), entry("v", "user", "Prompt   title")]
    create(cli, [header("main"), *prompt], name="session-main.jsonl")
    create(cli, [header("agent01", kind="subagent"), *prompt], name="parent/agent01.jsonl")
    legacy = cli.root / "sources/gemini-cli/.gemini/tmp/project/chats/session-legacy.json"
    legacy.write_text(json.dumps({**header("legacy"), "messages": [entry("a", "user", "Legacy")]}, indent=2))
    create(cli, [header("resumed"), entry("a", "user", "Resumed")], name="session-resumed.jsonl")
    (legacy.parent / "session-resumed.json").write_text(
        json.dumps({**header("resumed"), "messages": [entry("a", "user", "Old snapshot")]})
    )
    create(cli, [header("empty")], name="session-empty.jsonl")
    create(cli, [entry("u", "user", "No session id")], name="session-anonymous.jsonl")
    create(cli, [header("checkpoint"), *prompt], name="../checkpoint.jsonl")
    create(cli, [header("elsewhere"), *prompt], name="../logs/session-elsewhere.jsonl")

    sessions = run_json(cli, "--list", "-d", "36500", "-q", "provider:gemini-cli")
    assert {item["id"]: item["title"] for item in sessions} == {
        "main": "Prompt title",
        "agent01": "Prompt title",
        "legacy": "Legacy",
        "resumed": "Resumed",
    }
    assert len(sessions) == 4
    assert run_json(cli, "gemini-cli://agent01", "--head")["message_count"] == 2
    assert cli.run("rust", "gemini-cli://empty", "--head").returncode == 1


def test_gemini_cli_home_is_a_home_directory(cli):
    home = Path(cli.environment["HOME"])
    create(cli, [header("default"), entry("u", "user", "Default")], root=home)
    create(cli, [header("custom"), entry("u", "user", "Custom")], root=home / "custom")

    cli.environment.pop("GEMINI_CLI_HOME")
    assert set(listed(cli)) == {"default"}
    cli.environment["GEMINI_CLI_HOME"] = "~/custom"
    assert set(listed(cli)) == {"custom"}
