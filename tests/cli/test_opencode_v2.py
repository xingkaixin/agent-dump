"""OpenCode V2 authoritative rows, visible messages and outer decoding failures."""

import json
import sqlite3

from opencode_fixtures import insert_message
import pytest
from sqlite_fixture import create_legacy, create_v2


@pytest.fixture
def database(cli, monkeypatch):
    return create_v2(cli, monkeypatch)


def test_v2_lists_visible_messages_and_full_token_totals(cli, database):
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_v2 SET title = NULL, tokens_reasoning = 2, tokens_cache_read = 8, tokens_cache_write = 1"
        )
        insert_message(connection, "idle", {"outcome": "succeeded"}, seq=3)
    listing = cli.run("rust", "--list", "-d", "36500", "-q", "provider:opencode", "--lang", "en")
    assert listing.returncode == 0, listing.stderr
    assert "OpenCode V2 prompt" in listing.stdout
    assert "msgs=2" in listing.stdout
    result = cli.run("rust", "opencode://ses_v2", "--format", "json", "--output", "exports", "--lang", "en")
    assert result.returncode == 0, result.stderr
    data = json.loads((cli.root / "exports/opencode/ses_v2.json").read_text())
    assert data["title"] == "OpenCode V2 prompt"
    assert [message["id"] for message in data["messages"]] == ["msg_1", "msg_2"]
    assert data["stats"] == {
        "total_cost": 0.5,
        "total_input_tokens": 109,
        "total_output_tokens": 22,
        "message_count": 2,
        "total_tokens": 131,
    }


@pytest.mark.differential
@pytest.mark.parametrize(
    "kind,data",
    [
        ("assistant", {"content": None}),
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


@pytest.mark.differential
def test_missing_projection_table_keeps_head_unknown_and_body_fails(cli, database):
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE session_message")
    cli.parity("opencode://ses_v2", "--head", "--lang", "en")
    for candidate in ("python", "rust"):
        assert cli.run(candidate, "opencode://ses_v2", "--format", "raw", "--output", "exports").returncode == 1
