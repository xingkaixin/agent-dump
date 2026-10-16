import json
import sqlite3

from desktop_fixture import desktop, exports
import pytest

pytestmark = pytest.mark.differential


@pytest.mark.parametrize("status", ["success", "granted", "pending", "loading", "new"])
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


def test_drafts_and_missing_metadata(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "deepchat")
    with sqlite3.connect(cli.source) as conn:
        conn.execute(
            "INSERT INTO new_sessions SELECT 'draft', agent_id, title, NULL, 1, session_kind, NULL, created_at, updated_at FROM new_sessions"
        )
        conn.execute("DELETE FROM deepchat_sessions")
    cli.parity("--list", "-d", "36500", "-q", "provider:deepchat", "--lang", "en")
    exports(cli, "deepchat", identity)
