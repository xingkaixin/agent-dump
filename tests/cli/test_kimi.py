"""Kimi context and legacy wire contracts through the published CLI surface."""

import hashlib
import json
import os
import shutil

from cli_fixture import IDENTITY, provider_export, write_jsonl
import pytest


def create(cli, *, context=None, wire=None, metadata=None, cwd="/workspace/kimi"):
    root = cli.root / "sources/kimi"
    project = hashlib.md5(cwd.encode(), usedforsecurity=False).hexdigest() if cwd else "unresolved-project"
    directory = root / "sessions" / project / IDENTITY
    directory.mkdir(parents=True, exist_ok=True)
    (root / "kimi.json").write_text(json.dumps({"work_dirs": [{"path": cwd}]}))
    path = directory / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "session_id": IDENTITY,
                "title": " Kimi  会话 ",
                "createdAt": 1768478400000,
                "wire_mtime": 1768478400,
                **(metadata or {}),
            }
        )
    )
    os.utime(path, (1768478400, 1768478400))
    for name, records in (("context.jsonl", context), ("wire.jsonl", wire)):
        if records is not None:
            write_jsonl(directory / name, records)
            os.utime(directory / name, (1768478400, 1768478400))
    return directory


def call(identity="call", name="Shell", arguments='{"command":"pwd"}', **fields):
    return {"type": "function", "id": identity, "function": {"name": name, "arguments": arguments}, **fields}


def wire_event(kind, **payload):
    return {"timestamp": 1768478400.123, "message": {"type": kind, "payload": payload}}


CONTEXT_STREAM = [
    {"role": "_checkpoint"},
    {"role": "user", "content": "Start"},
    {
        "role": "assistant",
        "content": [{"type": "think", "think": "Reason"}, {"type": "text", "text": "Execute"}],
        "tool_calls": [call()],
    },
    {"role": "tool", "tool_call_id": "call", "content": [{"type": "text", "text": "Result"}, "More"]},
    {"role": "tool", "tool_call_id": "call", "content": "Again"},
    {"role": "_usage", "token_count": 14},
    {"role": "_usage", "token_count": 31.9},
]


@pytest.mark.differential
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_context_usage_head_list_and_exports(cli, lang):
    create(cli, context=CONTEXT_STREAM)
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", lang)
    cli.parity("--list", "-d", "36500", "-q", "provider:kimi", "--lang", lang)
    provider_export(cli, f"kimi://{IDENTITY}", "kimi", lang=lang)


@pytest.mark.differential
@pytest.mark.parametrize("arguments", ['{"z":1,"a":2}', "invalid", "null", "[]", None, 4, {"z": "中文"}])
def test_context_tool_arguments(cli, arguments):
    create(
        cli,
        context=[
            {"role": "assistant", "tool_calls": [call(arguments=arguments)]},
            {"role": "tool", "tool_call_id": "call", "content": "OK"},
        ],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.differential
@pytest.mark.parametrize(
    "content",
    [None, "", False, 1e-6, {"z": 1, "a": "中文"}, ["one", {"type": "text", "text": "two"}, {"type": "image"}, None]],
)
def test_context_output_shapes_and_orphans(cli, content):
    create(
        cli,
        context=[
            {"role": "assistant", "tool_calls": [call()]},
            *({"role": "tool", "tool_call_id": identity, "content": content} for identity in ("call", "unknown", "")),
        ],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.differential
def test_context_todo_filtering_and_title_mapping(cli):
    names = ["SetTodoList", "ReadFile", "Glob", "StrReplaceFile", "Grep", "WriteFile", "Shell", "Unknown"]
    create(
        cli,
        context=[
            {"role": "assistant", "tool_calls": [call(name, name) for name in names]},
            *({"role": "tool", "tool_call_id": name, "content": "Result"} for name in names),
        ],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.differential
def test_context_user_coercion_empty_and_unknown_records(cli):
    create(
        cli,
        context=[{"role": "user", "content": value} for value in ["", "   "]]
        + [{"role": "unknown", "content": "ignored"}],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


def test_context_reads_string_and_joins_part_list_with_spaces(cli):
    pasted = [
        {"type": "text", "text": "Review "},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA==", "id": None}},
        {"type": "text", "text": "PASTED BODY"},
        {"type": "text", "text": " then reply"},
    ]
    create(
        cli,
        context=[
            {"role": "user", "content": "Plain prompt"},
            {"role": "assistant", "content": "Plain answer"},
            {"role": "user", "content": pasted},
        ],
    )
    result = cli.run("rust", f"kimi://{IDENTITY}", "--read", "--json", "--order", "asc")
    assert result.returncode == 0, result.stderr
    messages = json.loads(result.stdout)["data"]["messages"]
    assert [(item["role"], item["text"]) for item in messages] == [
        ("user", "Plain prompt"),
        ("assistant", "Plain answer"),
        ("user", "Review   PASTED BODY  then reply"),
    ]


WIRE_STREAM = [
    wire_event("TurnBegin", user_input=[{"text": "Start"}]),
    wire_event("ContentPart", type="think", think="Think"),
    wire_event("ContentPart", type="text", text="Running"),
    wire_event("ToolCall", id="call", function={"name": "Shell", "arguments": '{"command":'}),
    wire_event("ToolCallPart", arguments_part='"pwd"}'),
    wire_event("ToolResult", tool_call_id="call", return_value={"z": "value", "a": [1e-6]}),
    wire_event("ToolResult", tool_call_id="call", return_value="Again"),
    wire_event("TurnBegin", user_input=[{"text": "Next"}]),
    wire_event("ContentPart", type="text", text="Done"),
]


@pytest.mark.differential
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_wire_assembly_streaming_arguments_and_unknown_head_count(cli, lang):
    create(cli, wire=WIRE_STREAM)
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", lang)
    cli.parity("--list", "-d", "36500", "-q", "provider:kimi", "--lang", lang)
    provider_export(cli, f"kimi://{IDENTITY}", "kimi", lang=lang)


@pytest.mark.differential
@pytest.mark.parametrize(
    "records",
    [
        [
            wire_event("ContentPart", type="text", text="Owner"),
            wire_event("ToolResult", tool_call_id="missing", return_value="Orphan"),
            wire_event("ToolCall", id="call", function={"name": "ReadFile", "arguments": "{}"}),
            wire_event("ToolResult", tool_call_id="call", return_value="Result"),
        ],
        [
            wire_event("ToolCall", id="todo", function={"name": "SetTodoList", "arguments": "{"}),
            wire_event("ToolCallPart", arguments_part='"items":[]}'),
            wire_event("ToolResult", tool_call_id="todo", return_value="Ignored"),
            wire_event("ContentPart", type="text", text="Keep"),
        ],
        [
            wire_event("ContentPart", type="unknown"),
            wire_event("ToolCall", id="bad", function=None),
            wire_event("ToolCallPart", arguments_part="ignored"),
            wire_event("ContentPart", type="text", text="Keep"),
        ],
        [
            wire_event("ToolCall", id="a", function={"name": "ReadFile", "arguments": "{"}),
            wire_event("ToolCallPart", arguments_part='"incomplete":'),
            wire_event("TurnBegin", user_input=[]),
            wire_event("ToolCallPart", arguments_part="3}"),
            wire_event("ContentPart", type="text", text="Keep"),
        ],
    ],
)
def test_wire_boundaries(cli, records):
    create(cli, wire=records)
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


def test_wire_user_input_keeps_strings_and_joins_parts_with_spaces(cli):
    pasted = [
        {"type": "text", "text": "Review "},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        {"type": "text", "text": "PASTED BODY"},
        {"type": "text", "text": " then reply"},
    ]
    create(cli, wire=[wire_event("TurnBegin", user_input="Plain prompt"), wire_event("TurnBegin", user_input=pasted)])
    result = cli.run("rust", f"kimi://{IDENTITY}", "--read", "--json", "--order", "asc")
    assert result.returncode == 0, result.stderr
    messages = json.loads(result.stdout)["data"]["messages"]
    assert [(item["role"], item["text"]) for item in messages] == [
        ("user", "Plain prompt"),
        ("user", "Review   PASTED BODY  then reply"),
    ]


@pytest.mark.differential
@pytest.mark.parametrize("timestamp", [None, "1768478400", True, 1e30, -1e30, 0, 1768478400.123])
def test_wire_timestamps_and_token_count_coercion(cli, timestamp):
    record = wire_event("TurnBegin", user_input=[{"text": "Keep"}])
    record["timestamp"] = timestamp
    create(
        cli,
        wire=[record, {"role": "_usage", "token_count": 12}, {"role": "_usage", "token_count": "ignored"}],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.differential
@pytest.mark.parametrize(
    "metadata,cwd",
    [
        ({}, ""),
        ({"wire_mtime": 1e30}, "/workspace/kimi"),
        ({"wire_mtime": "invalid"}, "/workspace/kimi"),
    ],
)
def test_metadata_identity_title_time_and_working_directory_fallback(cli, metadata, cwd):
    create(cli, context=CONTEXT_STREAM, metadata=metadata, cwd=cwd)
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.differential
def test_metadata_mtime_does_not_hide_a_current_wire_mtime(cli):
    directory = create(cli, context=CONTEXT_STREAM)
    os.utime(directory / "metadata.json", (0, 0))
    cli.parity("--list", "-d", "36500", "-q", "provider:kimi", "--lang", "en")
    cli.parity("--list", "-d", "1", "-q", "provider:kimi", "--lang", "en")


@pytest.mark.differential
def test_large_context_head_keeps_count_unknown(cli):
    create(cli, context=[{"role": "user", "content": "x" * 300_000}])
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.differential
def test_local_fallback_and_project_hash_map(cli):
    create(cli, context=CONTEXT_STREAM)
    shutil.move(str(cli.root / "sources/kimi/sessions"), cli.root / "data/kimi")
    shutil.move(str(cli.root / "sources/kimi/kimi.json"), cli.root / "data/kimi.json")
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", "en")


def test_exports_cannot_write_into_kimi_sources(cli):
    create(cli, context=CONTEXT_STREAM)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(
        "rust", f"kimi://{IDENTITY}", "--format", "json,md,raw", "--output", str(cli.root / "sources/kimi")
    )
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.differential
@pytest.mark.parametrize("metadata", ["{broken", "[]"])
def test_bad_metadata_does_not_hide_healthy_sessions(cli, metadata):
    directory = create(cli, context=CONTEXT_STREAM)
    bad = directory.parent / "bad-session"
    bad.mkdir()
    (bad / "metadata.json").write_text(metadata)
    write_jsonl(bad / "context.jsonl", [{"role": "user", "content": "ignored"}])
    before = cli.fixtures.source_manifest(cli.root)
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "--list", "-d", "36500", "-q", "provider:kimi", "--lang", "en")
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"kimi://{IDENTITY}" in result.stdout
        assert "bad-session" not in result.stdout.split("URI:")[-1]
        assert "metadata.json" in result.stderr, result.stdout + result.stderr
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")
    assert cli.fixtures.source_manifest(cli.root) == before


def export(cli):
    result = cli.run("rust", f"kimi://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    return json.loads(next((cli.root / "exports/kimi").glob("*.json")).read_text())


def status(**usage):
    return wire_event("StatusUpdate", token_usage=usage)


def test_state_json_title_fallback_times_and_configured_model(cli):
    directory = create(
        cli,
        wire=[
            wire_event(
                "TurnBegin", user_input=[{"text": "<system-reminder>hidden</system-reminder>\n  First   line\nmore"}]
            )
        ],
        metadata={"title": "Ignored metadata"},
    )
    (directory / "state.json").write_text(
        json.dumps({"custom_title": "", "createdAt": "2026-01-15T12:00:00Z", "wire_mtime": 1768478500})
    )
    os.utime(directory / "wire.jsonl", (1768478460, 1768478460))
    untitled = directory.parent / "untitled"
    nested = directory / "nested/deeper"
    for path in (untitled, nested):
        path.mkdir(parents=True)
        (path / "metadata.json").write_text("{}")
        write_jsonl(path / "context.jsonl", [{"role": "assistant", "content": "No prompt"}])
    (cli.root / "sources/kimi/config.toml").write_text(
        'default_model = "kimi-code/kimi-for-coding"\n\n'
        '[models."moonshot-cn/kimi-k2.5"]\nmodel = "kimi-k2.5"\n\n'
        '[models."kimi-code/kimi-for-coding"]\nmodel = "kimi-for-coding"\n'
    )
    result = cli.run("rust", "--list", "-d", "36500", "-q", "provider:kimi", "--json")
    assert result.returncode == 0, result.stderr
    sessions = {item["id"]: item for item in json.loads(result.stdout)["data"]}
    assert sessions.keys() == {IDENTITY, "untitled"}
    assert sessions["untitled"]["title"] == "Untitled Session"
    head = sessions[IDENTITY]
    assert (head["title"], head["created_at"], head["updated_at"], head["model"]) == (
        "First line",
        "2026-01-15T12:00:00.000000+00:00",
        "2026-01-15T12:01:40.000000+00:00",
        "kimi-for-coding",
    )


def test_status_usage_counts_cache_and_subagents_and_marks_wire_messages(cli):
    directory = create(
        cli,
        wire=[
            wire_event("TurnBegin", user_input=[{"text": "Start"}]),
            wire_event("ContentPart", type="text", text="Answer"),
            status(input_other=20, output=8, input_cache_read=5, input_cache_creation=2),
            status(input_other=1, output=1),
            {"message": {"usage": {"input_tokens": 100, "output_tokens": 100}}},
        ],
    )
    write_jsonl(directory / "subagents/a1/wire.jsonl", [status(input_other=30, output=6, input_cache_read=10)])
    (cli.root / "sources/kimi/config.toml").write_text('default_model = "kimi-k2"\n')
    payload = export(cli)
    assert (payload["stats"]["total_input_tokens"], payload["stats"]["total_output_tokens"]) == (68, 15)
    user, assistant = payload["messages"]
    assert user["tokens"] == {}
    assert assistant["model"] == "kimi-k2"
    assert assistant["tokens"] == {"input": 28, "output": 9, "cache": {"read": 5, "write": 2}}


def test_context_keeps_untyped_tool_calls_and_leaves_usage_on_stats(cli):
    untyped = {"id": "call", "function": {"name": "Shell", "arguments": '{"command":"pwd"}'}}
    create(
        cli,
        context=[
            {"role": "assistant", "tool_calls": [untyped]},
            {"role": "tool", "tool_call_id": "call", "content": "OK"},
        ],
        wire=[status(input_other=3, output=2, input_cache_read=1)],
    )
    payload = export(cli)
    assert (payload["stats"]["total_input_tokens"], payload["stats"]["total_output_tokens"]) == (4, 2)
    [message] = payload["messages"]
    assert message["tokens"] == {}
    [part] = message["parts"]
    assert (part["tool"], part["state"]["arguments"]) == ("Shell", {"command": "pwd"})
    assert [item["text"] for item in part["state"]["output"]] == ["OK"]
