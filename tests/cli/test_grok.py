"""Grok CLI sessions through the published CLI surface."""

import json

from cli_fixture import IDENTITY, write_jsonl

STAMP = 1768478400 * 1000
XAI = "_x.ai/session/update"


def create(cli, updates, *, summary=None, project="project", directory=IDENTITY):
    session = cli.root / "sources/grok/sessions" / project / directory
    session.mkdir(parents=True, exist_ok=True)
    if summary is not None:
        (session / "summary.json").write_text(json.dumps(summary))
    if updates is not None:
        write_jsonl(session / "updates.jsonl", updates)
    return session


def summary(identity=IDENTITY, cwd="/workspace/grok", **fields):
    return {"info": {"id": identity, "cwd": cwd}, "created_at": "2026-01-15T12:00:00Z", **fields}


def update(kind, offset=0, prompt="p1", method="session/update", **fields):
    meta = {"agentTimestampMs": STAMP + offset, "promptId": prompt, "eventId": f"event-{offset}"}
    return {"method": method, "params": {"update": {"sessionUpdate": kind, **fields}, "_meta": meta}}


def user(body, offset=0, index=0):
    return update("user_message_chunk", offset, content={"type": "text", "text": body}, _meta={"promptIndex": index})


def agent(body, offset=0, prompt="p1", kind="agent_message_chunk"):
    return update(kind, offset, prompt, content={"type": "text", "text": body})


def xai(kind, offset=0, **fields):
    return update(kind, offset, method=XAI, **fields)


def run_json(cli, *args):
    result = cli.run("rust", *args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def listed(cli):
    return {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:grok")}


STREAM = [
    user("<system-reminder>hidden</system-reminder>\nFix   the bug", 1),
    user("\nmore", 2),
    update("current_mode_update", 3, currentModeId="agent"),
    agent("Reason", 4, kind="agent_thought_chunk"),
    agent("ing", 5, kind="agent_thought_chunk"),
    update(
        "tool_call",
        6,
        toolCallId="bash",
        title="Run",
        rawInput={"command": "pwd"},
        _meta={"x.ai/tool": {"name": "run_terminal_command", "kind": "execute"}},
    ),
    update(
        "tool_call_update",
        7,
        toolCallId="bash",
        status="failed",
        content=[{"type": "content", "content": {"type": "text", "text": "denied"}}],
    ),
    update("plan", 8, entries=[{"content": "Inspect", "status": "pending"}]),
    update("plan", 9, entries=[{"content": "Inspect", "status": "completed"}]),
    agent("Done", 10),
    xai(
        "turn_completed",
        11,
        usage={
            "inputTokens": 10,
            "outputTokens": 4,
            "cachedReadTokens": 2,
            "reasoningTokens": 1,
            "totalTokens": 14,
            "costUsdTicks": 25_000_000,
        },
    ),
    user("Discard", 12, index=1),
    agent("Discarded", 13, prompt="p2"),
    xai("turn_completed", 14, usage={"inputTokens": 5, "outputTokens": 5}),
    xai("rewind_marker", 15, target_prompt_index=1),
    user("Replace", 16, index=1),
    xai("model_changed", 17, model_id="grok-code-fast"),
    agent("Replaced", 18, prompt="p3"),
    xai("turn_completed", 19, usage={"inputTokens": 3, "outputTokens": 1, "cacheCreationTokens": 2}),
]


def test_list_head_and_export(cli):
    session = create(cli, STREAM, summary=summary(current_model_id="grok-4", last_active_at="2026-01-15T13:00:00Z"))
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli)[IDENTITY]
    keys = ("title", "created_at", "updated_at", "model", "message_count", "working_directory")
    assert {key: record[key] for key in keys} == {
        "title": "Fix the bug",
        "created_at": "2026-01-15T12:00:00.000000+00:00",
        "updated_at": "2026-01-15T13:00:00.000000+00:00",
        "model": "grok-code-fast",
        "message_count": 4,
        "working_directory": "/workspace/grok",
    }
    head = run_json(cli, f"grok://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record

    result = cli.run("rust", f"grok://{IDENTITY}", "--format", "json,raw", "--output", "exports")
    assert result.returncode == 0, result.stderr
    exports = cli.root / "exports/grok"
    assert (exports / f"{IDENTITY}.raw.jsonl").read_bytes() == (session / "updates.jsonl").read_bytes()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before

    assert payload["stats"] == {
        "total_cost": 0.0025,
        "total_input_tokens": 18,
        "total_output_tokens": 10,
        "message_count": 4,
        "total_tokens": 28,
        "total_cache_read_tokens": 2,
        "total_cache_create_tokens": 2,
    }
    first, answer, replaced, reply = payload["messages"]
    assert (first["id"], [part["text"] for part in first["parts"]]) == ("event-1", ["Fix   the bug\nmore"])
    assert (answer["id"], answer["agent"], answer["provider"], answer["model"], answer["mode"]) == (
        "p1",
        "grok",
        "xai",
        "grok-4",
        "tool",
    )
    assert (answer["cost"], answer["tokens"]) == (
        0.0025,
        {"input": 10, "output": 4, "reasoning": 1, "cache": {"read": 2, "write": 0}},
    )
    reasoning, tool, plan, text = answer["parts"]
    assert (reasoning["type"], reasoning["text"]) == ("reasoning", "Reasoning")
    assert (tool["tool"], tool["title"], tool["state"]) == (
        "run_terminal_command",
        "bash",
        {
            "status": "error",
            "input": {"command": "pwd"},
            "output": None,
            "metadata": {"kind": "execute"},
            "error": "denied",
        },
    )
    assert (plan["type"], plan["input"], plan["approval_status"]) == ("plan", "- [x] Inspect", "success")
    assert text["text"] == "Done"
    assert (replaced["id"], replaced["parts"][0]["text"]) == ("event-16", "Replace")
    assert (reply["model"], reply["parts"][0]["text"], reply["tokens"]) == (
        "grok-code-fast",
        "Replaced",
        {"input": 3, "output": 1, "cache": {"read": 0, "write": 2}},
    )


def test_discovery_needs_identity_cwd_and_messages(cli):
    prompt = [user("Prompt title")]
    titled = {"generated_title": "Generated title", "session_summary": "Summary title"}
    create(cli, prompt, summary=summary("generated", **titled), directory="generated")
    create(cli, prompt, summary=summary("summarized", session_summary="Summary title"), directory="summarized")
    create(cli, prompt, summary=summary("prompted"), project="a/b/c", directory="prompted")
    image = update("user_message_chunk", content={"type": "image", "data": "AA==", "mimeType": "image/png"})
    create(cli, [image], summary=summary("image", cwd="/work/basename-dir"), directory="image")
    create(cli, prompt, summary=summary("renamed"), directory="folder")
    create(cli, prompt, summary={"info": {"id": "no-cwd"}}, directory="no-cwd")
    create(cli, prompt, summary={"info": {"cwd": "/no-id"}}, directory="no-id")
    create(cli, None, summary=summary("no-updates"), directory="no-updates")
    create(cli, prompt, directory="no-summary")
    create(cli, [xai("turn_completed", usage={"inputTokens": 1})], summary=summary("empty"), directory="empty")

    sessions = listed(cli)
    assert {key: item["title"] for key, item in sessions.items()} == {
        "generated": "Generated title",
        "summarized": "Summary title",
        "prompted": "Prompt title",
        "image": "basename-dir",
        "renamed": "Prompt title",
    }
    assert run_json(cli, "grok://renamed", "--head")["id"] == "renamed"
    assert cli.run("rust", "grok://empty", "--head").returncode == 1
