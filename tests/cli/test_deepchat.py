import json
import sqlite3

from desktop_fixture import desktop, exports
import pytest


@pytest.mark.parametrize("drop", [False, True])
def test_fallback_compaction_and_block_types(tmp_path, monkeypatch, drop):
    cli, identity = desktop(tmp_path, monkeypatch, "deepchat")
    blocks = [
        {"type": "reasoning_content", "content": "private"},
        {"type": "error", "content": "failed"},
        {"type": "plan", "content": "plan", "extra": {"steps": [1, 2]}, "status": "success"},
        {"type": "image", "image_data": {"mimeType": "image/png", "data": "sample"}},
        {"type": "action", "content": "internal", "action_type": "approval"},
        {"type": "content", "content": "Visible answer"},
    ]
    with sqlite3.connect(cli.source) as conn:
        statements = (
            ("DROP TABLE deepchat_user_messages", "DROP TABLE deepchat_assistant_blocks")
            if drop
            else ("DELETE FROM deepchat_user_messages", "DELETE FROM deepchat_assistant_blocks")
        )
        for statement in statements:
            conn.execute(statement)
        conn.execute("UPDATE deepchat_messages SET content = ? WHERE role = 'assistant'", (json.dumps(blocks),))
        conn.execute(
            "INSERT INTO deepchat_messages SELECT 'compaction', session_id, 3, role, content, status, ?, created_at, updated_at FROM deepchat_messages WHERE role = 'assistant'",
            ('{"messageType":"compaction"}',),
        )
    data = exports(cli, "deepchat", identity)
    assert data["messages"][2]["role"] == "compaction"
    assert [p["type"] for p in data["messages"][1]["parts"]] == [
        "reasoning",
        "text",
        "plan",
        "image",
        "deepchat_action",
        "text",
    ]


@pytest.mark.parametrize("status", ["success", "granted", "error", "denied", "pending", "loading", "new"])
@pytest.mark.parametrize("structured", [False, True])
def test_tool_states_and_streaming_arguments(tmp_path, monkeypatch, status, structured):
    cli, identity = desktop(tmp_path, monkeypatch, "deepchat")
    with sqlite3.connect(cli.source) as conn:
        conn.execute("DELETE FROM deepchat_assistant_blocks")
        if structured:
            conn.execute(
                "INSERT INTO deepchat_assistant_blocks (message_id, block_index, block_type, status, tool_call_id, tool_name, tool_params, tool_response, extra_json, updated_at) VALUES ('assistant-1', 0, 'tool_call', ?, 'call', 'read', ?, ?, ?, 987)",
                (
                    status,
                    '{"path":',
                    "result",
                    json.dumps({"timestamp": 123, "toolCallExtra": {"mcpResult": {"isError": False}}}),
                ),
            )
        else:
            conn.execute(
                "UPDATE deepchat_messages SET content = ? WHERE role = 'assistant'",
                (
                    json.dumps(
                        [
                            {
                                "type": "tool_call",
                                "status": status,
                                "timestamp": 123,
                                "tool_call": {
                                    "id": "call",
                                    "name": "read",
                                    "params": '{"path":',
                                    "response": "result",
                                    "mcpResult": {"isError": False},
                                },
                            }
                        ]
                    ),
                ),
            )
    part = exports(cli, "deepchat", identity)["messages"][1]["parts"][0]
    assert part["state"]["input"] == '{"path":'
    assert part["time_created"] == 123


@pytest.mark.parametrize("structured", [False, True])
def test_attachments_links_and_message_sequence(tmp_path, monkeypatch, structured):
    cli, identity = desktop(tmp_path, monkeypatch, "deepchat")
    with sqlite3.connect(cli.source) as conn:
        if structured:
            conn.execute(
                "INSERT INTO deepchat_user_message_files VALUES ('user-1', 0, 'image', '/not-read/image.png', 'image/png', 5, '{}')"
            )
            conn.execute(
                "INSERT INTO deepchat_user_message_links VALUES ('user-1', 0, 'https://example.invalid/not-fetched')"
            )
        else:
            conn.execute("DELETE FROM deepchat_user_messages")
            conn.execute(
                "UPDATE deepchat_messages SET content = ? WHERE role = 'user'",
                (
                    json.dumps(
                        {
                            "text": "prompt",
                            "files": [
                                {"name": "image", "path": "/not-read/image.png", "mimeType": "image/png", "size": 5},
                                "bad",
                            ],
                            "links": ["https://example.invalid/not-fetched"],
                        }
                    ),
                ),
            )
        conn.execute("UPDATE deepchat_messages SET created_at = 1 WHERE role = 'assistant'")
    data = exports(cli, "deepchat", identity)
    assert [m["id"] for m in data["messages"]] == ["user-1", "assistant-1"]
    assert data["messages"][0]["attachments"][0]["path"] == "/not-read/image.png"


def test_drafts_window_and_missing_metadata(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "deepchat")
    with sqlite3.connect(cli.source) as conn:
        conn.execute(
            "INSERT INTO new_sessions SELECT 'draft', agent_id, title, NULL, 1, session_kind, NULL, created_at, updated_at FROM new_sessions"
        )
        conn.execute(
            "INSERT INTO new_sessions SELECT 'old', agent_id, '', NULL, 0, session_kind, NULL, 1, 1 FROM new_sessions WHERE id = ?",
            (identity,),
        )
        conn.execute("DELETE FROM deepchat_sessions")
    cli.parity("--list", "-d", "36500", "-q", "provider:deepchat", "--lang", "en")
    cli.parity("deepchat://old", "--head", "--lang", "en")
    exports(cli, "deepchat", identity)
