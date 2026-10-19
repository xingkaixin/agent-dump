"""Factory Droid sessions through the published CLI surface."""

import json

from cli_fixture import IDENTITY, write_jsonl


def factory(cli):
    return cli.root / "sources/droid/.factory"


def create(cli, records, *, start=None, settings=None, folder="", identity=IDENTITY):
    path = factory(cli) / "sessions" / folder / f"{identity}.jsonl"
    if start is not None:
        records = [{"type": "session_start", "id": identity, **start}, *records]
    write_jsonl(path, records)
    if settings is not None:
        path.with_suffix(".settings.json").write_text(json.dumps(settings))
    return path


def message(role, content, offset=0, identity="m", **fields):
    stamp = f"2026-01-15T12:{offset // 60:02}:{offset % 60:02}Z"
    return {
        "type": "message",
        "id": identity,
        "timestamp": stamp,
        "message": {"role": role, "content": content, **fields},
    }


def run_json(cli, *args):
    result = cli.run(*args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def listed(cli):
    return {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:droid")}


TRANSCRIPT = [
    message(
        "user", [{"type": "text", "text": "<system-reminder>Env</system-reminder>"}, {"type": "text", "text": "Fix"}]
    ),
    message("user", [{"type": "text", "text": "Hidden context"}], 1, visibility="llm_only"),
    message(
        "assistant",
        [
            {"type": "thinking", "thinking": "Check logs", "signature": "s"},
            {"type": "text", "text": "Running checks"},
            {"type": "tool_use", "id": "t1", "name": "Execute", "input": {"command": "make"}},
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "main.rs"}},
        ],
        5,
        "a1",
    ),
    message(
        "user",
        [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "make failed"},
            {"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "fn main() {}"}]},
        ],
        9,
    ),
    {"type": "todo_state", "id": "todo", "todos": []},
    message("assistant", "Fixed", 60, "a2"),
]


def test_list_head_and_export(cli):
    (factory(cli) / "settings.json").parent.mkdir(parents=True)
    (factory(cli) / "settings.json").write_text(
        json.dumps({"customModels": [{"id": "custom:Sonnet-0", "model": "claude-sonnet-4-5"}]})
    )
    source = create(
        cli,
        TRANSCRIPT,
        start={"title": "New Session", "cwd": "/workspace", "lastCwd": "/workspace/app"},
        settings={
            "model": "custom:Sonnet-0",
            "tokenUsage": {"inputTokens": 100, "outputTokens": 50, "cacheCreationTokens": 10, "cacheReadTokens": 1000},
        },
        folder="-workspace-app",
    )
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli)[IDENTITY]
    assert {key: record[key] for key in ("title", "created_at", "updated_at", "model", "message_count")} == {
        "title": "Fix",
        "created_at": "2026-01-15T12:00:00.000000+00:00",
        "updated_at": "2026-01-15T12:01:00.000000+00:00",
        "model": "claude-sonnet-4-5",
        "message_count": 3,
    }
    assert record["working_directory"] == "/workspace/app"
    head = run_json(cli, f"droid://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record

    result = cli.run(f"droid://{IDENTITY}", "--format", "json,md,raw", "--output", "exports")
    assert result.returncode == 0, result.stderr
    exports = cli.root / "exports/droid"
    assert (exports / f"{IDENTITY}.raw.jsonl").read_bytes() == source.read_bytes()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before

    assert payload["stats"] == {
        "total_cost": 0,
        "total_input_tokens": 1110,
        "total_output_tokens": 50,
        "message_count": 3,
    }
    user, assistant, final = payload["messages"]
    assert [part["text"] for part in user["parts"]] == ["Fix"]
    assert (assistant["id"], assistant["agent"]) == ("a1", "droid")
    reasoning, text, execute, read = assistant["parts"]
    assert (reasoning["type"], reasoning["text"], text["text"]) == ("reasoning", "Check logs", "Running checks")
    assert (execute["title"], execute["state"]["status"]) == ("Tool: Execute", "error")
    assert [part["text"] for part in execute["state"]["output"]] == ["make failed"]
    assert (read["state"]["status"], read["state"]["input"]) == ("completed", {"file_path": "main.rs"})
    assert [part["text"] for part in read["state"]["output"]] == ["fn main() {}"]
    assert [part["text"] for part in final["parts"]] == ["Fixed"]


def test_discovery_reads_sessions_and_titles_like_codesesh(cli):
    prompt = [message("user", "Prompt title")]
    create(cli, prompt, start={"sessionTitle": "Named", "title": "Ignored"}, identity="named")
    create(cli, prompt, start={"title": "New Session"}, identity="prompted")
    create(cli, [message("assistant", "Done")], start={"cwd": "/workspace/repo"}, identity="folder")
    create(cli, prompt, start={"callingSessionId": "named"}, folder="nested", identity="child")
    create(cli, prompt, identity="no-start")
    create(cli, [message("user", "Hidden", visibility="llm_only")], start={}, identity="hidden")
    create(cli, prompt, start={}, folder="a/b", identity="too-deep")

    sessions = listed(cli)
    assert {key: item["title"] for key, item in sessions.items()} == {
        "named": "Named",
        "prompted": "Prompt title",
        "folder": "repo",
        "child": "Prompt title",
    }
    assert cli.run("droid://hidden", "--head").returncode == 1
