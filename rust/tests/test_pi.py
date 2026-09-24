"""Pi tree entries, content and metadata through both public CLI implementations."""

from pathlib import Path
import shutil

from cli_fixture import IDENTITY, STAMP, provider_export, write_jsonl
import pytest


def create(cli, records, *, header=None, filename=None, suffix=b""):
    path = cli.root / "sources/pi/agent/sessions/project" / (filename or f"20260115_{IDENTITY}.jsonl")
    return write_jsonl(
        path,
        [
            {
                "type": "session",
                "id": IDENTITY,
                "version": 3,
                "cwd": "/workspace/pi",
                "timestamp": STAMP,
                **(header or {}),
            },
            *records,
        ],
        suffix=suffix,
    )


def message(role, content=None, *, identity="entry", parent=None, **fields):
    return {
        "type": "message",
        "id": identity,
        "parentId": parent,
        "timestamp": STAMP,
        "message": {"role": role, "content": content, **fields},
    }


STREAM = [
    message("user", "Start", identity="user"),
    message(
        "assistant",
        [
            {"type": "thinking", "thinking": " Think "},
            {"type": "text", "text": " Read "},
            {"type": "toolCall", "name": "read", "id": "call", "arguments": {"path": "file.py"}},
        ],
        identity="assistant",
        parent="user",
        provider="anthropic",
        model="claude",
        usage={
            "input": 10,
            "output": 5,
            "totalTokens": 15,
            "cost": {"total": 0.01},
        },
    ),
    message(
        "toolResult",
        [{"type": "text", "text": "Result"}],
        identity="result",
        parent="assistant",
        toolName="read",
        toolCallId="call",
    ),
    message("assistant", "Branch A", identity="branch-a", parent="user"),
    message("assistant", "Branch B", identity="branch-b", parent="user"),
    {"type": "compaction", "id": "compact", "summary": "Compact summary", "timestamp": STAMP},
    {"type": "branch_summary", "summary": "Branch summary", "timestamp": STAMP},
    {"type": "custom_message", "content": "Custom entry", "timestamp": STAMP},
    {"type": "session_info", "name": " Latest\nTitle ", "timestamp": "2026-01-17T00:00:00Z"},
    {"type": "unknown", "timestamp": "2026-01-14T00:00:00Z"},
]


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_tree_messages_titles_stats_list_head_and_exports(cli, lang):
    create(cli, STREAM)
    cli.parity("--list", "-d", "36500", "-q", "provider:pi", "--lang", lang)
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", lang)
    provider_export(cli, f"pi://{IDENTITY}", "pi", lang=lang)


@pytest.mark.parametrize(
    "content",
    [
        "  Keep whitespace  ",
        None,
        5,
        [],
        ["  Keep whitespace  ", 7, None, {"type": "text", "text": None}, {"type": "thinking", "thinking": False}],
        [{"type": "image", "mimeType": " image/png ", "data": "AA=="}, {"type": "image"}],
        [{"type": "toolCall", "name": "custom", "id": "call", "arguments": None}],
        [{"type": "toolCall", "name": " ", "id": ""}, {"type": "unknown", "text": "Ignored"}],
    ],
)
def test_content_shapes_images_and_tools(cli, content):
    create(cli, [message("assistant", content)])
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.parametrize(
    "role,fields",
    [
        ("bashExecution", {"command": " pwd ", "output": " /workspace "}),
        ("bashExecution", {"command": "", "output": ""}),
        ("bashExecution", {"command": None, "output": None}),
        ("toolResult", {"toolName": "", "toolCallId": "", "isError": True}),
        ("toolResult", {"toolName": None, "toolCallId": None, "isError": [1]}),
        ("branchSummary", {"summary": " Branch "}),
        ("compactionSummary", {"summary": None}),
        ("custom", {}),
        ("future-role", {}),
        ("system", {}),
        ("developer", {}),
    ],
)
def test_special_roles(cli, role, fields):
    create(cli, [message(role, "Visible", **fields)])
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.parametrize("identity,parent", [(None, None), (7, False), ("", "previous"), ("  id  ", {}), ([], [])])
def test_entry_identifiers_parents_and_valid_record_numbering(cli, identity, parent):
    source = create(cli, [message("user", "Keep", identity=identity, parent=parent)])
    source.write_bytes(source.read_bytes().replace(b"\n", b"\n\n", 1))
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.parametrize(
    "timestamp",
    [None, True, "bad", 0, -0.9, 1768478400123.456, 1e30, "2026-01-15T12:00:00", "2026-01-15T20:00:00+08:00"],
)
def test_message_and_header_timestamps(cli, timestamp):
    create(cli, [message("user", "Keep", timestamp=timestamp)], header={"timestamp": timestamp})
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.parametrize(
    "usage",
    [
        {"input": "4", "output": 2.9, "totalTokens": "6", "cost": {"total": "0.1"}},
        {"input": True, "output": None, "totalTokens": "bad", "cost": {"total": "NaN"}},
        {"cost": {"total": True}},
        {"cost": None},
    ],
)
def test_usage_accumulates_even_without_visible_parts(cli, usage):
    create(cli, [message("assistant", "", usage=usage), message("assistant", "Visible", usage=usage)])
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.parametrize(
    "header,records",
    [
        ({"cwd": ""}, []),
        ({"version": None}, [message("user", [{"type": "thinking", "thinking": "Title from thinking"}])]),
        ({}, [message("user", "   "), message("user", "Useful title")]),
        ({}, [{"type": "message", "message": None}, {"type": "session_info", "name": "  "}]),
    ],
)
def test_metadata_fallback_and_raw_message_count(cli, header, records):
    create(cli, records, header=header)
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"pi://{IDENTITY}", "pi")


def test_large_scan_and_full_read_resolve_different_titles(cli):
    create(
        cli, [message("user", "x" * 300_000), {"type": "session_info", "name": "Full read title"}, {"type": "unknown"}]
    )
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"pi://{IDENTITY}", "pi")


def test_header_identity_fallback_lookup_and_incomplete_tail(cli):
    create(cli, [message("user", "Keep")], filename="mismatched-name.jsonl", suffix=b'{"type":')
    provider_export(cli, f"pi://{IDENTITY}", "pi")


def test_local_fallback(cli):
    create(cli, STREAM)
    shutil.move(str(cli.root / "sources/pi/agent/sessions"), cli.root / "data/pi")
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")


def test_invalid_header_is_not_a_pi_session(cli):
    create(cli, [message("user", "Keep")], header={"type": "message"})
    cli.parity("--list", "-d", "36500", "-q", "provider:pi", "--lang", "en")


def test_exports_cannot_write_into_pi_sources(cli):
    create(cli, STREAM)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"pi://{IDENTITY}", "--format", "json,md,raw", "--output", str(cli.root / "sources/pi"))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("root", ["", "relative provider", "~/literal-provider", " "])
def test_environment_paths_follow_python_path_semantics(cli, root):
    create(cli, STREAM)
    target = Path(cli.environment["HOME"]) / ".pi" if root == "" else cli.root / root
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cli.root / "sources/pi"), target)
    cli.environment["PI_HOME"] = root
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")
