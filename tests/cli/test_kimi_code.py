"""Kimi-Code wire sessions through the published CLI surface."""

import json
import os

from cli_fixture import IDENTITY, write_jsonl

STAMP = 1768478400


def create(cli, wire, *, state=None, bucket="hash", identity=IDENTITY):
    directory = cli.root / "sources/kimi-code/sessions" / bucket / identity
    directory.mkdir(parents=True, exist_ok=True)
    if state is not None:
        (directory / "state.json").write_text(json.dumps(state))
        os.utime(directory / "state.json", (STAMP, STAMP))
    if wire is not None:
        write_jsonl(directory / "agents/main/wire.jsonl", wire)
    return directory


def appended(role, content, time=STAMP * 1000, **fields):
    return {"type": "context.append_message", "time": time, "message": {"role": role, "content": content, **fields}}


def loop(time=STAMP * 1000, **event):
    return {"type": "context.append_loop_event", "time": time, "event": event}


def run_json(cli, *args):
    result = cli.run("rust", *args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def listed(cli):
    return {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:kimi-code")}


STREAM = [
    {"type": "llm.request", "model": "kimi-k2", "provider": "moonshot"},
    appended("user", "<system-reminder>hidden</system-reminder>\nFix   the bug\nmore"),
    loop(type="content.part", part={"type": "think", "think": "Reason"}),
    loop(type="content.part", part={"type": "plan", "text": "Plan steps", "approved": False}),
    loop(
        type="content.part",
        part={"type": "image", "source": {"kind": "base64", "data": "AA==", "media_type": "image/png"}},
    ),
    loop(type="tool.call", name="Bash", toolCallId="bash", args={"command": "pwd"}),
    loop(type="tool.result", toolCallId="bash", result={"output": "failed", "isError": True, "note": "try again"}),
    loop(type="tool.call", name="SetTodoList", toolCallId="todo", args={}),
    loop(type="tool.result", toolCallId="todo", result={"output": "hidden"}),
    {"type": "usage.record", "usage": {"inputOther": 10, "inputCacheRead": 2, "inputCacheCreation": 3, "output": 4}},
    loop(type="step.begin"),
    appended(
        "assistant",
        [{"type": "text", "text": "Done"}],
        toolCalls=[{"id": "read", "function": {"name": "ReadFile", "arguments": '{"path":"a.rs"}'}}],
    ),
    appended("tool", [{"type": "text", "text": "fn main() {}"}], toolCallId="read"),
    {"type": "context.apply_compaction", "time": STAMP * 1000, "summary": "Earlier work"},
]


def test_list_head_and_export(cli):
    directory = create(cli, STREAM, state={"createdAt": STAMP * 1000, "workDir": "/workspace/kimi-code"})
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli)[IDENTITY]
    assert {key: record[key] for key in ("title", "created_at", "model", "message_count", "working_directory")} == {
        "title": "Fix the bug",
        "created_at": "2026-01-15T12:00:00.000000+00:00",
        "model": "kimi-k2",
        "message_count": 4,
        "working_directory": "/workspace/kimi-code",
    }
    head = run_json(cli, f"kimi-code://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record

    result = cli.run("rust", f"kimi-code://{IDENTITY}", "--format", "json,md,raw", "--output", "exports")
    assert result.returncode == 0, result.stderr
    exports = cli.root / "exports/kimi-code"
    assert (exports / f"{IDENTITY}.raw.jsonl").read_bytes() == (directory / "agents/main/wire.jsonl").read_bytes()
    assert "## 4. Compaction\n\nEarlier work" in (exports / f"{IDENTITY}.md").read_text()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before

    assert payload["stats"] == {
        "total_cost": 0,
        "total_input_tokens": 15,
        "total_output_tokens": 4,
        "message_count": 4,
        "total_tokens": 19,
    }
    user, first, second, compaction = payload["messages"]
    assert [part["text"] for part in user["parts"]] == ["Fix   the bug\nmore"]
    assert (first["agent"], first["model"], first["provider"], first["mode"]) == (
        "kimi-code",
        "kimi-k2",
        "moonshot",
        "tool",
    )
    assert first["tokens"] == {"input": 15, "output": 4, "cache": {"read": 2, "write": 3}}
    reasoning, plan, image, bash = first["parts"]
    assert reasoning == {"type": "reasoning", "text": "Reason", "time_created": STAMP * 1000}
    assert (plan["type"], plan["input"], plan["approval_status"]) == ("plan", "Plan steps", "fail")
    assert (image["type"], image["mime_type"], image["data"]) == ("image", "image/png", "AA==")
    assert (bash["title"], bash["state"]["status"], bash["state"]["input"]) == ("bash", "error", {"command": "pwd"})
    assert bash["state"]["metadata"] == {"note": "try again"}
    assert [part["text"] for part in bash["state"]["output"]] == ["failed"]
    text, read = second["parts"]
    assert text["text"] == "Done"
    assert (read["title"], read["state"]["status"], read["state"]["input"]) == ("read", "completed", {"path": "a.rs"})
    assert [part["text"] for part in read["state"]["output"]] == ["fn main() {}"]
    assert (compaction["role"], compaction["parts"][0]["text"]) == ("compaction", "Earlier work")


def test_discovery_needs_state_and_wire_and_skips_empty_sessions(cli):
    prompt = [appended("user", "Prompt title")]
    create(cli, prompt, state={"title": "State title", "workDir": "/state"}, identity="state")
    create(cli, prompt, state={"customTitle": "Custom title", "custom": {"cwd": "/custom"}}, identity="custom")
    indexed = create(cli, prompt, state={}, identity="indexed")
    (cli.root / "sources/kimi-code/session_index.jsonl").write_text(
        json.dumps({"sessionDir": str(indexed), "workDir": "/indexed"}) + "\n"
    )
    create(cli, None, state={}, identity="no-wire")
    create(cli, prompt, identity="no-state")
    create(cli, [{"type": "llm.request", "model": "kimi-k2"}], state={}, identity="empty")
    create(cli, prompt, state={}, bucket="hash/nested", identity="too-deep")

    sessions = listed(cli)
    assert {key: (item["title"], item["working_directory"]) for key, item in sessions.items()} == {
        "state": ("State title", "/state"),
        "custom": ("Custom title", "/custom"),
        "indexed": ("Prompt title", "/indexed"),
    }
    missing = cli.run("rust", "kimi-code://empty", "--head")
    assert missing.returncode == 1
