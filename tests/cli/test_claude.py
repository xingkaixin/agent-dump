"""Claude Code behavior through Python and Rust CLIs on isolated synthetic projects."""

import json
import shutil

from cli_fixture import IDENTITY, STAMP, write_jsonl


def event(role, content, *, identity="event", **fields):
    return {
        "type": role,
        "uuid": identity,
        "timestamp": STAMP,
        "cwd": "/workspace/claude",
        "version": "1.0",
        "message": {"role": role, "content": content},
        **fields,
    }


def tool(identity="call", name="Read", **fields):
    return {"type": "tool_use", "id": identity, "name": name, "input": {"path": "file.py"}, **fields}


def result(identity="call", content="contents", **fields):
    return {"type": "tool_result", "tool_use_id": identity, "content": content, **fields}


def create(cli, records, *, identity=IDENTITY, project="-workspace-claude"):
    return write_jsonl(cli.root / "sources" / "claude" / "projects" / project / f"{identity}.jsonl", records)


def test_tool_result_is_error_marks_only_that_tool_failed(cli):
    create(
        cli,
        [
            event("assistant", [tool(), tool("other", "Bash")]),
            event("user", [result(content="boom", is_error=True), result("other")]),
        ],
    )
    result_ = cli.run(f"claude://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result_.returncode == 0, result_.stderr
    export = json.loads(next((cli.root / "exports/claudecode").glob("*.json")).read_text())
    states = {part["callID"]: part["state"] for message in export["messages"] for part in message["parts"]}
    assert states["call"]["status"] == "error"
    assert states["other"]["status"] == "completed"


def test_exports_cannot_write_into_claude_sources(cli):
    create(cli, [event("user", "Start")])
    before = cli.fixtures.source_manifest(cli.root)
    result_ = cli.run(f"claude://{IDENTITY}", "--format", "json,md,raw", "--output", str(cli.root / "sources/claude"))
    assert result_.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


def test_non_string_index_summary_falls_back_to_message_title(cli):
    index = create(cli, [event("user", "Fallback title")]).with_name("sessions-index.json")
    index.write_text(json.dumps({"entries": [{"sessionId": IDENTITY, "summary": {"text": "bad"}}]}))
    for args in (("--list", "-q", "provider:claude", "-d", "36500"), (f"claude://{IDENTITY}", "--head")):
        result_ = cli.run(*args, "--lang", "en")
        assert result_.returncode == 0, result_.stderr
        assert "Fallback title" in result_.stdout
        assert len(result_.stderr.splitlines()) == 1 and str(index) in result_.stderr


def test_system_tags_and_trailing_whitespace_are_removed(cli):
    create(
        cli,
        [
            event(
                "user",
                "<command-name>/clear</command-name>\n<command-message>clear</command-message>\n<command-args></command-args>",
                identity="command",
            ),
            event("user", "Fix it  \n<system-reminder>internal</system-reminder>", identity="prompt"),
            event(
                "assistant",
                [{"type": "text", "text": "Done <system-reminder>hidden</system-reminder>\n"}, tool()],
                identity="answer",
            ),
            event("user", [result(content="ok  \n<system-reminder>hidden</system-reminder>")], identity="output"),
        ],
    )
    completed = cli.run(f"claude://{IDENTITY}", "--format", "json", "--output", "exports", "--lang", "en")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(next((cli.root / "exports/claudecode").glob("*.json")).read_text())
    messages = payload["messages"]
    assert [message["id"] for message in messages] == ["prompt", "answer"]
    assert messages[0]["parts"][0]["text"] == "Fix it"
    text, call = messages[1]["parts"]
    assert text["text"] == "Done"
    assert call["state"]["output"][0]["text"] == "ok"


def rust_json(cli, *args):
    completed = cli.run(*args, "--lang", "en")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


def rust_export(cli, identity=IDENTITY):
    shutil.rmtree(cli.root / "exports", ignore_errors=True)
    rust_json(cli, f"claude://{identity}", "--format", "json", "--output", "exports")
    return json.loads(next((cli.root / "exports/claudecode").glob("*.json")).read_text())


def listed(cli):
    document = json.loads(rust_json(cli, "--list", "--json", "-d", "36500", "-q", "provider:claude").stdout)
    return {item["id"]: item for item in document["data"]}


def test_discovery_uses_visible_records_titles_and_subagents(cli):
    later = "2026-01-15T12:05:00+00:00"
    first = event("user", "First prompt  \nsecond line", identity="prompt")
    first.pop("cwd")
    create(
        cli,
        [
            first,
            event("assistant", [tool("spawn", "Agent")], identity="spawn", cwd="/workspace/late"),
            {"type": "ai-title", "aiTitle": "Generated"},
            {"type": "custom-title", "customTitle": "Old name"},
            {"type": "custom-title", "customTitle": "New name\nignored"},
            event("assistant", [{"type": "text", "text": "Done"}], identity="done", timestamp=later),
            {"type": "last-prompt", "timestamp": "2026-01-15T13:00:00+00:00"},
        ],
    )
    create(
        cli,
        [
            *[{"type": "progress", "timestamp": STAMP}] * 20,
            event("user", "Too late for a title"),
        ],
        identity="late-prompt",
    )
    create(
        cli,
        [
            event("user", "<local-command-stdout>ok</local-command-stdout>"),
            event("user", "Hidden", isMeta=True),
            {"type": "progress", "timestamp": STAMP},
        ],
        identity="hidden",
    )
    session = cli.root / "sources/claude/projects/-workspace-claude" / IDENTITY / "subagents"
    for path, meta in [
        (session / "agent-a1.jsonl", {"agentId": "worker", "name": "Worker title", "toolUseId": "spawn"}),
        (session / "workflows/run/agent-a2.jsonl", {"description": "Flow description"}),
        (session / "workflows/run/journal.jsonl", None),
    ]:
        write_jsonl(path, [event("user", "Subagent prompt")])
        if meta:
            path.with_suffix(".meta.json").write_text(json.dumps(meta))

    records = listed(cli)
    assert set(records) == {IDENTITY, "late-prompt", "worker", "a2"}
    parent = records[IDENTITY]
    assert parent["title"] == "New name"
    assert parent["working_directory"] == "/workspace/late"
    assert parent["updated_at"].startswith("2026-01-15T12:05:00")
    assert parent["message_count"] == 3
    assert records["late-prompt"]["title"] == "claude"
    assert records["worker"]["title"] == "Worker title"
    assert records["a2"]["title"] == "Flow description"
    assert rust_export(cli, "worker")["messages"][0]["parts"][0]["text"] == "Subagent prompt"
    spawn = next(message for message in rust_export(cli)["messages"] if message["id"] == "spawn")
    assert spawn["subagent_id"] == "worker"


def test_large_session_lists_exact_visible_count(cli):
    create(
        cli,
        [
            event("user", "Start"),
            event("assistant", [{"type": "text", "text": "x" * 300_000}]),
            {"type": "custom-title", "customTitle": "Late title"},
            event("user", [result()]),
        ],
    )
    record = listed(cli)[IDENTITY]
    assert record["title"] == "Late title"
    assert record["message_count"] == 2
    assert record["message_count_completeness"] == "exact"


def test_transcript_keeps_tools_images_and_request_usage(cli):
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}

    def assistant(identity, request, content, usage):
        record = event("assistant", content, identity=identity, requestId=request)
        record["message"].update(model="claude-test", usage=usage)
        return record

    create(
        cli,
        [
            event("user", "Start", identity="start"),
            assistant(
                "think",
                "first",
                [{"type": "thinking", "thinking": "Plan"}],
                {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 5},
            ),
            assistant(
                "todo",
                "first",
                [tool("todo", "TodoWrite")],
                {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "cache_read_input_tokens": 5,
                    "cache_creation_input_tokens": 2,
                },
            ),
            event(
                "user",
                [result("todo", [{"type": "text", "text": "Saved"}, image])],
                identity="saved",
                toolUseResult={"success": True, "commandName": "todo"},
            ),
            assistant("empty", "second", [], {"input_tokens": 3, "output_tokens": 2}),
            assistant("read", "third", [tool("read")], {"input_tokens": 1, "output_tokens": 1}),
        ],
    )
    payload = rust_export(cli)
    messages = {message["id"]: message for message in payload["messages"]}
    assert list(messages) == ["start", "think", "empty", "read"]
    reasoning, todo = messages["think"]["parts"]
    assert reasoning["type"] == "reasoning"
    assert messages["think"]["mode"] is None
    assert messages["think"]["tokens"]["output_tokens"] == 4
    assert todo["tool"] == "TodoWrite"
    assert todo["state"]["status"] == "completed"
    assert todo["state"]["metadata"] == {"commandName": "todo"}
    assert todo["state"]["output"] == [
        {"type": "text", "text": "Saved", "time_created": todo["time_created"]},
        {"type": "image", "mime_type": "image/png", "data": "iVBORw0KGgo=", "time_created": todo["time_created"]},
    ]
    assert messages["empty"]["parts"] == []
    assert messages["read"]["parts"][0]["state"]["status"] == "running"
    assert payload["stats"]["total_input_tokens"] == 17 + 3 + 1
    assert payload["stats"]["total_output_tokens"] == 4 + 2 + 1
