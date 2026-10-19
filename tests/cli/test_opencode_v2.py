"""OpenCode V2 authoritative rows, visible messages and outer decoding failures."""

import json
import sqlite3

from opencode_fixtures import insert_message
import pytest
from sqlite_fixture import create_v2


@pytest.fixture
def database(cli, monkeypatch):
    return create_v2(cli, monkeypatch)


def test_v2_lists_visible_messages_and_full_token_totals(cli, database):
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_v2 SET title = NULL, tokens_reasoning = 2, tokens_cache_read = 8, tokens_cache_write = 1"
        )
        insert_message(connection, "idle", {"outcome": "succeeded"}, seq=3)
    listing = cli.run("--list", "-d", "36500", "-q", "provider:opencode", "--lang", "en")
    assert listing.returncode == 0, listing.stderr
    assert "OpenCode V2 prompt" in listing.stdout
    assert "msgs=2" in listing.stdout
    result = cli.run("opencode://ses_v2", "--format", "json", "--output", "exports", "--lang", "en")
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
