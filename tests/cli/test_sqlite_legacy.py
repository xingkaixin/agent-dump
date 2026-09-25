"""Legacy OpenCode and ZCode transcript and read-only database contracts."""

import json
import sqlite3
import sys

import pytest
from sqlite_fixture import NOW, create_legacy, export

PROVIDERS = [
    "opencode",
    pytest.param(
        "zcode",
        marks=pytest.mark.skipif(
            not sys.platform.startswith(("darwin", "win")), reason="ZCode supports macOS and Windows"
        ),
    ),
]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_legacy_list_head_and_all_formats(cli, provider, lang):
    create_legacy(cli, provider)
    cli.parity("--list", "-d", "36500", "-q", f"provider:{provider}", "--lang", lang)
    cli.parity(f"{provider}://ses_old", "--head", "--lang", lang)
    export(cli, provider, "ses_old", lang=lang)
    raw = json.loads((cli.root / "exports" / provider / "ses_old.raw.json").read_text())
    assert raw["messages"][-1]["role"] == "developer"


@pytest.mark.parametrize(
    "part",
    [
        {
            "type": "tool",
            "tool": "bash",
            "callID": "call",
            "title": "Run",
            "state": {"input": {"command": "pwd"}, "output": [{"type": "text", "text": "OK"}]},
        },
        {"type": "tool", "tool": 7, "callID": None, "state": []},
        {"type": "step-start", "reason": None, "tokens": {}, "cost": None},
        {"type": "step-finish", "reason": "stop", "tokens": {"input": 4}, "cost": "0.3"},
        {"type": "text", "text": 5},
        {"type": "reasoning", "text": None},
        {"type": "future", "text": "Must not become visible"},
        {"type": None},
    ],
)
def test_part_shapes_and_unknown_types(cli, part):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO part VALUES ('extra', 'msg_assistant', ?, ?)", (NOW + 50, json.dumps(part)))
    export(cli, identity="ses_old")


@pytest.mark.parametrize(
    "fields",
    [
        {
            "time": "bad",
            "tokens": "bad",
            "cost": "invalid",
            "modelID": 7,
            "agent": [],
            "mode": False,
            "providerID": None,
        },
        {"time": {"completed": "preserve"}, "tokens": {"input": "4", "output": 2.9}, "cost": "0.25"},
        {"time": {"completed": {"raw": 1}}, "tokens": {"input": True, "output": None}, "cost": "NaN"},
        {"role": "other", "cost": True},
    ],
)
def test_message_scalar_coercion(cli, fields):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE message SET data = ? WHERE id = 'msg_assistant'", (json.dumps({"role": "assistant", **fields}),)
        )
    export(cli, identity="ses_old")


@pytest.mark.parametrize(
    "summary",
    [
        None,
        "",
        "  plain.py  ",
        ' ["x", 3, null, "  "] ',
        "a" * 80,
        '["' + "a" * 60 + '", "' + "b" * 60 + '", "c", "d", "e", "f"]',
    ],
)
def test_head_summary_targets_and_nullable_metadata(cli, summary):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE session SET title = NULL, directory = NULL, slug = NULL, version = NULL, summary_files = ?",
            (summary,),
        )
    cli.parity("opencode://ses_old", "--head", "--lang", "en")
    export(cli, identity="ses_old")


def test_missing_message_table_keeps_head_count_unknown(cli):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE message")
    cli.parity("opencode://ses_old", "--head", "--lang", "en")
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "opencode://ses_old", "--format", "json,raw", "--output", "exports")
        assert result.returncode == 1
    assert not any(path.is_file() for path in (cli.root / "exports").rglob("*"))


def test_parts_are_batched_without_losing_messages_or_order(cli):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        for index in range(1003):
            identity = f"msg_{index}"
            connection.execute(
                "INSERT INTO message VALUES (?, 'ses_old', ?, ?)", (identity, NOW + 10 + index, '{"role":"user"}')
            )
            connection.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?)",
                (identity, identity, NOW, json.dumps({"type": "text", "text": f"body {index}"})),
            )
    export(cli, identity="ses_old")


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_database_and_wal_remain_unchanged_and_new_commits_are_visible(cli, journal):
    path = create_legacy(cli)
    writer = sqlite3.connect(path)
    try:
        writer.execute(f"PRAGMA journal_mode={journal}")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        for body in ("Initial commit", "Committed update"):
            writer.execute(
                "UPDATE part SET data = ? WHERE id = 'part_0'", (json.dumps({"type": "text", "text": body}),)
            )
            writer.commit()
            files = sorted(path.parent.iterdir())
            durable = {item: item.read_bytes() for item in files if not item.name.endswith("-shm")}
            payloads = []
            for candidate in ("python", "rust"):
                result = cli.run(
                    candidate, "opencode://ses_old", "--format", "json", "--output", "exports", "--lang", "en"
                )
                assert result.returncode == 0, result.stdout + result.stderr
                data = json.loads((cli.root / "exports/opencode/ses_old.json").read_text())
                assert data["messages"][0]["parts"][0]["text"] == body
                payloads.append((result.stdout, result.stderr, data))
                assert sorted(path.parent.iterdir()) == files
                assert all(item.read_bytes() == content for item, content in durable.items())
            assert payloads[0] == payloads[1]
    finally:
        writer.close()


def test_exports_cannot_write_inside_database_source(cli):
    path = create_legacy(cli)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "opencode://ses_old", "--format", "json,md,raw", "--output", str(path.parent))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before
