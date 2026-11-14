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


def _tool_content(name: str, *, status: str = "completed", **state):
    return {"type": "tool", "id": f"call_{name}", "name": name, "state": {"status": status, **state}}


def test_v2_links_only_unambiguous_task_and_subagent_children(cli, database):
    cases = [
        ([_tool_content("task", metadata={"sessionId": "child_a"})], "child_a"),
        ([_tool_content("task", metadata={"sessionID": "child_b"})], "child_b"),
        ([_tool_content("subagent", metadata={"sessionId": "child_c"})], "child_c"),
        (
            [
                _tool_content("task", metadata={"sessionId": "child_d"}),
                _tool_content("subagent", metadata={"sessionID": "child_d"}),
            ],
            "child_d",
        ),
        (
            [
                _tool_content("task", metadata={"sessionId": "child_e"}),
                _tool_content("task", metadata={"sessionId": "child_f"}),
            ],
            None,
        ),
        ([_tool_content("task", metadata={"sessionId": "child_g", "sessionID": "child_h"})], None),
        ([_tool_content("task", metadata={"sessionId": "   "})], None),
        ([_tool_content("read", metadata={"sessionId": "child_i"})], None),
    ]
    with sqlite3.connect(database) as connection:
        for seq, (content, _) in enumerate(cases, start=3):
            insert_message(connection, "assistant", {"content": content}, seq=seq)
    result = cli.run("opencode://ses_v2", "--format", "json", "--output", "exports", "--lang", "en")
    assert result.returncode == 0, result.stderr
    data = json.loads((cli.root / "exports/opencode/ses_v2.json").read_text())
    actual = [message.get("subagent_id") for message in data["messages"][2:]]
    assert actual == [expected for _, expected in cases]


def test_v2_invalid_input_error_marks_tool_failed_without_guessing_other_tools(cli, database):
    error = "Invalid input for tool edit: JSON parsing failed"
    content = [
        _tool_content(
            "invalid",
            input={"tool": "edit", "error": error},
            content=[{"type": "text", "text": "[Old tool result content cleared]"}],
        ),
        _tool_content(
            "edit",
            input={"error": error},
            content=[{"type": "text", "text": "error mentioned in output"}],
        ),
        _tool_content("invalid", input={"tool": "edit", "error": "   "}, content=[]),
    ]
    with sqlite3.connect(database) as connection:
        insert_message(connection, "assistant", {"content": content}, seq=3)
    result = cli.run("opencode://ses_v2", "--format", "json", "--output", "exports", "--lang", "en")
    assert result.returncode == 0, result.stderr
    data = json.loads((cli.root / "exports/opencode/ses_v2.json").read_text())
    invalid_part, edit_part, blank_invalid_part = data["messages"][2]["parts"]
    assert invalid_part["state"]["status"] == "error"
    assert invalid_part["state"]["error"] == error
    assert invalid_part["state"]["output"] == [{"type": "text", "text": "[Old tool result content cleared]"}]
    assert edit_part["state"]["status"] == "completed"
    assert "error" not in edit_part["state"]
    assert blank_invalid_part["state"]["status"] == "completed"
    assert "error" not in blank_invalid_part["state"]
