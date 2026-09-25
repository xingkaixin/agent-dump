"""OpenCode V2 authoritative rows, coexistence and strict transcript decoding."""

import json
import sqlite3
import time

import pytest
from sqlite_fixture import create_legacy, create_v2, export


@pytest.fixture
def database(cli, monkeypatch):
    return create_v2(cli, monkeypatch)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_v2_list_head_and_all_formats(cli, database, lang):
    cli.parity("--list", "-d", "36500", "-q", "provider:opencode", "--lang", lang)
    cli.parity("opencode://ses_v2", "--head", "--lang", lang)
    export(cli, lang=lang)


@pytest.mark.parametrize(
    "kind,data",
    [
        ("user", {"text": "User", "files": [{"uri": "file:///never-read"}]}),
        ("system", {"text": "System"}),
        ("skill", {"text": "Skill", "name": "review"}),
        ("synthetic", {"text": "Automatic continuation"}),
        (
            "shell",
            {
                "shellID": "call",
                "command": "pwd",
                "status": "exited",
                "exit": 0,
                "output": {"output": "Done", "truncated": True},
            },
        ),
        ("compaction", {"summary": "Summary", "recent": "Recent", "status": "completed"}),
        ("agent-switched", {"agent": "plan"}),
        ("model-switched", {"model": {"id": "new"}}),
        ("location-switched", {"location": {"directory": "/new"}}),
        ("idle", {"outcome": "succeeded"}),
        ("future", {"text": "Metadata only", "content": [{"future": True}], "seq": 99}),
    ],
)
def test_message_kinds_preserve_metadata_and_seq_order(cli, database, kind, data):
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO session_message VALUES ('extra', 'ses_v2', ?, 3, 0, 0, ?)", (kind, json.dumps(data))
        )
    export(cli)


@pytest.mark.parametrize(
    "state",
    [
        {"status": "streaming", "input": '{"incomplete":'},
        {"status": "running", "input": {}, "content": []},
        {
            "status": "completed",
            "input": {"path": "a"},
            "content": [{"type": "text", "text": "Done"}, {"type": "file", "uri": "file:///never-read"}],
        },
        {"status": "error", "input": {}, "error": {"message": "Failed", "code": "example"}},
        {"status": "completed", "input": {}, "output": "retained", "content": [{"type": "other", "data": 5}]},
    ],
)
def test_tool_lifecycle_time_and_unmapped_content(cli, database, state):
    content = [
        {
            "type": "tool",
            "id": "tool",
            "name": "bash",
            "state": state,
            "time": {"created": "7"},
            "executed": True,
            "providerState": {"x": 1},
            "providerResultState": None,
        },
        {"type": "future-part", "text": "Retain in metadata"},
    ]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_message SET data = ? WHERE type = 'assistant'", (json.dumps({"content": content}),)
        )
    export(cli)


@pytest.mark.parametrize(
    "kind,data",
    [
        ("user", {"text": 7}),
        ("assistant", {"content": None}),
        ("assistant", {"content": ["invalid"]}),
        ("assistant", {"content": [{}]}),
        ("assistant", {"content": [{"type": "text", "text": None}]}),
        (
            "assistant",
            {"content": [{"type": "tool", "name": "bash", "id": "a", "state": {"status": "ok", "input": []}}]},
        ),
        ("assistant", {"content": [{"type": "tool", "name": "bash", "id": "a", "state": None}]}),
        (
            "assistant",
            {
                "content": [
                    {
                        "type": "tool",
                        "name": "bash",
                        "id": "a",
                        "state": {"status": "ok", "input": {}, "content": [{"type": "file", "uri": 4}]},
                    }
                ]
            },
        ),
        ("compaction", {"summary": None}),
        ("shell", {"command": "pwd"}),
        ("user", []),
        ("user", None),
    ],
)
def test_corrupt_v2_content_fails_all_exports_without_legacy_fallback(cli, database, kind, data):
    create_legacy(cli, path=database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE session SET id = 'ses_v2'")
        connection.execute("UPDATE session_message SET type = ?, data = ? WHERE id = 'msg_1'", (kind, json.dumps(data)))
    before = cli.fixtures.source_manifest(cli.root)
    cli.parity("opencode://ses_v2", "--head", "--lang", "en")
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "opencode://ses_v2", "--format", "json,md,raw,print", "--output", "exports")
        assert result.returncode == 1
        assert not any(path.is_file() for path in (cli.root / "exports").rglob("*"))
        assert cli.fixtures.source_manifest(cli.root) == before


def test_coexistence_prefers_v2_before_date_filtering(cli, database):
    create_legacy(cli, path=database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO session SELECT 'ses_v2', title, time_created, time_updated, slug, directory, version, summary_files FROM session"
        )
        connection.execute("UPDATE session_v2 SET time_created = 1")
        connection.execute("UPDATE session SET time_created = ? WHERE id = 'ses_v2'", (time.time_ns() // 1_000_000,))
    cli.parity("--list", "-d", "36500", "-q", "provider:opencode", "--lang", "en")
    cli.parity("--list", "-d", "1", "-q", "provider:opencode", "--lang", "en")
    export(cli)
    export(cli, identity="ses_old")


def test_missing_projection_table_keeps_head_unknown_and_body_fails(cli, database):
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE session_message")
    cli.parity("opencode://ses_v2", "--head", "--lang", "en")
    for candidate in ("python", "rust"):
        assert cli.run(candidate, "opencode://ses_v2", "--format", "raw", "--output", "exports").returncode == 1


@pytest.mark.parametrize("value", ["{broken", "[]", None, '{"id":7}', '{"id":"  spaced model  "}'])
def test_nullable_and_invalid_session_metadata(cli, database, value):
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_v2 SET model = ?, metadata = ?, revert = ?, fork_boundary = ?, title = NULL, directory = '', time_updated = 'invalid'",
            (value, value, value, value),
        )
    cli.parity("opencode://ses_v2", "--head", "--lang", "en")
    export(cli)


def test_session_totals_and_message_usage_remain_separate(cli, database):
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE session_v2 SET cost = 'NaN', tokens_input = 'invalid', tokens_output = 2.9")
        data = {
            "content": [],
            "cost": "0.1",
            "tokens": {"input": "4", "output": None},
            "time": {"completed": "5"},
            "agent": False,
            "model": [],
        }
        connection.execute("UPDATE session_message SET data = ? WHERE type = 'assistant'", (json.dumps(data),))
    export(cli)
