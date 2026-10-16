"""Pi tree entries, content and metadata through both public CLI implementations."""

import json
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


def message(role, content=None, *, identity=None, parent=None, **fields):
    tree = {} if identity is None else {"id": identity, "parentId": parent}
    return {"type": "message", **tree, "timestamp": STAMP, "message": {"role": role, "content": content, **fields}}


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


@pytest.mark.differential
@pytest.mark.parametrize(
    "content",
    [
        None,
        5,
        [],
        [{"type": "image", "mimeType": " image/png ", "data": "AA=="}, {"type": "image"}],
        [{"type": "toolCall", "name": "custom", "id": "call", "arguments": None}],
        [{"type": "toolCall", "name": " ", "id": ""}, {"type": "unknown", "text": "Ignored"}],
    ],
)
def test_content_shapes_images_and_tools(cli, content):
    create(cli, [message("assistant", content)])
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.differential
@pytest.mark.parametrize(
    "role,fields",
    [
        ("bashExecution", {"command": "", "output": ""}),
        ("branchSummary", {"summary": " Branch "}),
        ("compactionSummary", {"summary": None}),
        ("future-role", {}),
        ("system", {}),
        ("developer", {}),
    ],
)
def test_special_roles(cli, role, fields):
    create(cli, [message(role, "Visible", **fields)])
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.differential
@pytest.mark.parametrize("identity,parent", [(None, None), (7, False), ("", "previous"), ("  id  ", {}), ([], [])])
def test_entry_identifiers_parents_and_valid_record_numbering(cli, identity, parent):
    source = create(cli, [message("user", "Keep", identity=identity, parent=parent)])
    source.write_bytes(source.read_bytes().replace(b"\n", b"\n\n", 1))
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.differential
@pytest.mark.parametrize(
    "timestamp",
    [None, True, "bad", 0, -0.9, 1768478400123.456, 1e30, "2026-01-15T12:00:00", "2026-01-15T20:00:00+08:00"],
)
def test_message_and_header_timestamps(cli, timestamp):
    create(cli, [message("user", "Keep", timestamp=timestamp)], header={"timestamp": timestamp})
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.differential
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


@pytest.mark.differential
def test_large_scan_and_full_read_resolve_different_titles(cli):
    create(
        cli, [message("user", "x" * 300_000), {"type": "session_info", "name": "Full read title"}, {"type": "unknown"}]
    )
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.differential
def test_header_identity_fallback_lookup_and_incomplete_tail(cli):
    create(cli, [message("user", "Keep")], filename="mismatched-name.jsonl", suffix=b'{"type":')
    provider_export(cli, f"pi://{IDENTITY}", "pi")


@pytest.mark.differential
def test_local_fallback(cli):
    create(cli, STREAM)
    shutil.move(str(cli.root / "sources/pi/agent/sessions"), cli.root / "data/pi")
    cli.parity(f"pi://{IDENTITY}", "--head", "--lang", "en")


@pytest.mark.differential
def test_invalid_header_is_not_a_pi_session(cli):
    create(cli, [message("user", "Keep")], header={"type": "message"})
    cli.parity("--list", "-d", "36500", "-q", "provider:pi", "--lang", "en")


def test_exports_cannot_write_into_pi_sources(cli):
    create(cli, STREAM)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"pi://{IDENTITY}", "--format", "json,md,raw", "--output", str(cli.root / "sources/pi"))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize(
    "value,location",
    [
        ("", "home/.pi"),
        ("  ", "home/.pi"),
        ("relative provider", "relative provider"),
        (" ~/pi home ", "home/pi home"),
    ],
)
def test_environment_paths_trim_and_expand_home(cli, value, location):
    create(cli, STREAM)
    target = cli.root / location
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cli.root / "sources/pi"), target)
    cli.environment["PI_HOME"] = value
    result = cli.run("rust", f"pi://{IDENTITY}", "--head", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("layout", ["agent", "sessions", "settings", "relative-settings"])
def test_coding_agent_directories_take_precedence(cli, layout):
    create(cli, STREAM)
    agent = cli.root / "coding agent"
    target = agent / "sessions"
    if layout == "sessions":
        target = cli.root / "session override"
        cli.environment["PI_CODING_AGENT_SESSION_DIR"] = str(target)
    else:
        cli.environment["PI_CODING_AGENT_DIR"] = str(agent)
    if layout.endswith("settings"):
        directory = "relative sessions" if layout == "relative-settings" else str(cli.root / "settings sessions")
        if layout == "settings":
            target = Path(directory)
        agent.mkdir()
        (agent / "settings.json").write_text(json.dumps({"sessionDir": directory}))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cli.root / "sources/pi/agent/sessions"), target)
    result = cli.run("rust", f"pi://{IDENTITY}", "--head", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
