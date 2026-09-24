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
        json.dumps({"session_id": IDENTITY, "title": " Kimi\n会话 ", "wire_mtime": 1768478400, **(metadata or {})})
    )
    os.utime(path, (1768478400, 1768478400))
    if context is not None:
        write_jsonl(directory / "context.jsonl", context)
    if wire is not None:
        write_jsonl(directory / "wire.jsonl", wire)
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


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("with_wire", [True, False])
def test_context_precedence_usage_head_list_and_exports(cli, lang, with_wire):
    wire = (
        [
            wire_event("TurnBegin", user_input=[{"text": "Wire must not replace context"}]),
            {"message": {"usage": {"input_tokens": "7", "output_tokens": 2}}},
        ]
        if with_wire
        else None
    )
    create(cli, context=CONTEXT_STREAM, wire=wire)
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", lang)
    cli.parity("--list", "-d", "36500", "-q", "provider:kimi", "--lang", lang)
    provider_export(cli, f"kimi://{IDENTITY}", "kimi", lang=lang)


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


def test_context_user_coercion_empty_and_unknown_records(cli):
    create(
        cli,
        context=[{"role": "user", "content": value} for value in [None, "", "   ", ["quoted", {"value": True}], 7]]
        + [{"role": "assistant", "content": "ignored"}, {"role": "unknown", "content": "ignored"}],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


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


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_wire_assembly_streaming_arguments_and_unknown_head_count(cli, lang):
    create(cli, wire=WIRE_STREAM)
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", lang)
    cli.parity("--list", "-d", "36500", "-q", "provider:kimi", "--lang", lang)
    provider_export(cli, f"kimi://{IDENTITY}", "kimi", lang=lang)


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
            wire_event("StepBegin"),
            wire_event("StatusUpdate"),
            wire_event("ApprovalRequest"),
            wire_event("TurnBegin", user_input="ignored"),
            wire_event("ToolResult", return_value=["fallback"]),
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


@pytest.mark.parametrize("timestamp", [None, "1768478400", True, 1e30, -1e30, 0, 1768478400.123])
def test_wire_timestamps_and_usage_coercion(cli, timestamp):
    record = wire_event("TurnBegin", user_input=[{"text": "Keep"}])
    record["timestamp"] = timestamp
    create(
        cli,
        wire=[
            record,
            {"message": {"usage": {"input_tokens": True, "output_tokens": "bad"}}},
            {"message": {"usage": {"input_tokens": "9", "output_tokens": 2.9}}},
            {"role": "_usage", "token_count": 12},
            {"role": "_usage", "token_count": "ignored"},
        ],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.parametrize(
    "metadata,cwd",
    [
        ({}, ""),
        ({"title": "", "session_id": None}, "/workspace/kimi"),
        ({"title": 5, "session_id": 4}, ""),
        ({"wire_mtime": 1e30}, "/workspace/kimi"),
        ({"wire_mtime": "invalid"}, "/workspace/kimi"),
    ],
)
def test_metadata_identity_title_time_and_working_directory_fallback(cli, metadata, cwd):
    create(cli, context=CONTEXT_STREAM, metadata=metadata, cwd=cwd)
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


def test_metadata_mtime_does_not_hide_a_current_wire_mtime(cli):
    directory = create(cli, context=CONTEXT_STREAM)
    os.utime(directory / "metadata.json", (0, 0))
    cli.parity("--list", "-d", "36500", "-q", "provider:kimi", "--lang", "en")
    cli.parity("--list", "-d", "1", "-q", "provider:kimi", "--lang", "en")


def test_large_context_head_keeps_count_unknown(cli):
    create(cli, context=[{"role": "user", "content": "x" * 300_000}])
    cli.parity(f"kimi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


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
