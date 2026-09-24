import importlib
import sqlite3

from desktop_fixture import desktop, exports, fails
import pytest


def add_message(cli, data):
    with sqlite3.connect(cli.source) as conn:
        importlib.import_module("minimax_fixtures").insert_message(
            conn, {"msg_id": "extra", "role": "assistant", **data}
        )


@pytest.mark.parametrize("status", [1, 2, 3, 4, 5, 99])
def test_tool_lifecycle_and_partial_arguments(tmp_path, monkeypatch, status):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    add_message(
        cli,
        {
            "tool_calls": [
                {
                    "tool_name": "bash",
                    "tool_call_id": "call",
                    "tool_call_status": status,
                    "tool_call_args_delta": '{"command":',
                    "tool_call_result_data": "plain",
                }
            ]
        },
    )
    data = exports(cli, "minimax", identity)
    assert data["messages"][-1]["parts"][0]["state"]["input"] == '{"command":'


@pytest.mark.parametrize(
    "extra",
    [
        {"kind": "compaction_start"},
        {"kind": "review_result"},
        {"msg_type": 3},
        {"msg_type": 99},
        {"role": "user", "msg_content": "  <permission-response>yes"},
    ],
)
def test_internal_events_do_not_become_dialogue(tmp_path, monkeypatch, extra):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    add_message(cli, {"msg_content": "internal", **extra})
    data = exports(cli, "minimax", identity)
    assert data["messages"][-1]["parts"][0]["type"] == "minimax_event"


@pytest.mark.parametrize(
    "extra",
    [
        {"attachments": {}},
        {"tool_calls": [None]},
        {"tool_calls": [{"tool_name": 1}]},
        {"msg_content": []},
        {"thinking_content": 4},
    ],
)
def test_invalid_display_message_fails_whole_export(tmp_path, monkeypatch, extra):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    add_message(cli, extra)
    cli.parity(f"minimax://{identity}", "--head", "--lang", "en")
    fails(cli, f"minimax://{identity}")


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE local_runtime_sessions SET columnar_version = 2",
        "UPDATE local_runtime_sessions SET extra_data_json = '[]'",
        "UPDATE local_runtime_sessions SET created_at_ms = 'invalid'",
        "DELETE FROM local_runtime_message_row_migrations",
    ],
)
def test_unmigrated_or_invalid_sessions_fail_without_writing(tmp_path, monkeypatch, mutation):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    with sqlite3.connect(cli.source) as conn:
        conn.execute("INSERT INTO local_runtime_messages VALUES (?, '[{}]')", (identity,))
        conn.execute(mutation)
    fails(cli, f"minimax://{identity}")


@pytest.mark.parametrize(
    "title,workspace",
    [("  title\n\twith   spaces  ", "/workspace"), ("多" * 120, "/workspace"), (None, " /path/fallback/ "), ("", None)],
)
def test_title_fallback_and_unknown_facts(tmp_path, monkeypatch, title, workspace):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    with sqlite3.connect(cli.source) as conn:
        conn.execute(
            "UPDATE local_runtime_sessions SET title = ?, workspace_dir = ?, created_at_ms = NULL, extra_data_json = '{}'",
            (title, workspace),
        )
    cli.parity(f"minimax://{identity}", "--head", "--lang", "en")
    exports(cli, "minimax", identity)


def test_usage_attachments_and_id_order(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    add_message(
        cli,
        {
            "msg_content": "last despite older time",
            "timestamp": 1,
            "usage": {
                "input_tokens": True,
                "output_tokens": -1,
                "total_tokens": 0,
                "cache_read": "8",
                "cache_write": 3,
            },
            "attachments": [
                {
                    "meta": {"fileName": "spec", "mimeType": "text/plain", "attachmentType": "file", "sizeBytes": 9},
                    "local": {"filePath": "/not-read", "assetId": "asset"},
                    "cloud": {"url": "https://example.invalid/not-fetched"},
                }
            ],
        },
    )
    data = exports(cli, "minimax", identity)
    assert data["messages"][-1]["tokens"] == {"total": 0, "cache": {"write": 3}}


def test_session_visibility_and_archived_scope(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    with sqlite3.connect(cli.source) as conn:
        for key, runtime, visibility, kind, archived in [
            ("archived", "pi-agent", "visible", "conversation", 1),
            ("task", "pi-agent", "visible", "task", 0),
            ("unknown", "pi-agent", "visible", "unknown", 0),
            ("hidden", "pi-agent", "hidden", "conversation", 0),
            ("channel", "pi-agent", "visible", "channel", 0),
            ("old-runtime", "opencode", "visible", "conversation", 0),
        ]:
            conn.execute(
                "INSERT INTO local_runtime_sessions (session_id, runtime, visibility, session_kind, archived, created_at_ms, updated_at_ms) SELECT ?, ?, ?, ?, ?, created_at_ms, updated_at_ms FROM local_runtime_sessions WHERE session_id = ?",
                (key, runtime, visibility, kind, archived, identity),
            )
    cli.parity("--list", "-d", "36500", "-q", "provider:minimax", "--lang", "en")
