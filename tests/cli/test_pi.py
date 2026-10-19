"""Pi tree entries, content and metadata through both public CLI implementations."""

import json
from pathlib import Path
import shutil

from cli_fixture import IDENTITY, STAMP, write_jsonl
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
