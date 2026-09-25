"""SQLite JSON BLOBs follow each Provider's accepted input types."""

import sqlite3

from cli_fixture import make_cli
from desktop_fixture import desktop, exports, fails
import pytest
from sqlite_fixture import create_v2, export as sqlite_export
from test_cursor import cursor, export as cursor_export


@pytest.mark.parametrize(
    "encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"]
)
@pytest.mark.parametrize("provider", ["opencode", "minimax", "minimax-metadata", "cursor"])
def test_json_blob_decoding(tmp_path, monkeypatch, provider, encoding):
    if provider == "opencode":
        cli = make_cli(tmp_path, monkeypatch)
        cli.source = create_v2(cli, monkeypatch)
        select = "SELECT data FROM session_message WHERE type = 'assistant'"
        update = "UPDATE session_message SET data = ? WHERE type = 'assistant'"
    elif provider == "cursor":
        cli = cursor(tmp_path, monkeypatch)
        select = "SELECT value FROM cursorDiskKV WHERE key = 'bubbleId:parent:b-answer'"
        update = "UPDATE cursorDiskKV SET value = ? WHERE key = 'bubbleId:parent:b-answer'"
    else:
        cli, identity = desktop(tmp_path, monkeypatch, "minimax")
        if provider == "minimax":
            select = "SELECT data_json FROM local_runtime_message_rows WHERE msg_id = 'assistant-1'"
            update = "UPDATE local_runtime_message_rows SET data_json = ? WHERE msg_id = 'assistant-1'"
        else:
            select = "SELECT extra_data_json FROM local_runtime_sessions"
            update = "UPDATE local_runtime_sessions SET extra_data_json = ?"
    with sqlite3.connect(cli.source) as connection:
        original = connection.execute(select).fetchone()[0]
        connection.execute(update, (original.encode(encoding),))
    if provider == "opencode":
        sqlite_export(cli)
    elif provider == "cursor":
        cursor_export(cli)
    else:
        exports(cli, "minimax", identity)


@pytest.mark.parametrize("raw", [b'{"inputTokens":999}', b"\xff"])
def test_deepchat_blob_metadata_is_ignored(tmp_path, monkeypatch, raw):
    cli, identity = desktop(tmp_path, monkeypatch, "deepchat")
    with sqlite3.connect(cli.source) as connection:
        connection.execute("UPDATE deepchat_messages SET metadata = ?", (raw,))
    exports(cli, "deepchat", identity)


@pytest.mark.parametrize("raw", [b'{"parts":[]}', b"\xff"])
def test_cherry_blob_message_is_rejected(tmp_path, monkeypatch, raw):
    cli, identity = desktop(tmp_path, monkeypatch, "cherry")
    with sqlite3.connect(cli.source) as connection:
        connection.execute("UPDATE agent_session_message SET data = ? WHERE role = 'assistant'", (raw,))
    fails(cli, f"cherry://{identity}")


@pytest.mark.parametrize("raw", [b"\xff", b'{"broken":', b"\xff\xfe{\x00x", b"\xff\xfe\x00\x00{\x00\x00\x00x", 2, "[]"])
@pytest.mark.parametrize("provider", ["opencode", "minimax", "minimax-metadata"])
def test_json_cell_errors_keep_decoding_reason(tmp_path, monkeypatch, raw, provider):
    if provider == "opencode":
        cli = make_cli(tmp_path, monkeypatch)
        cli.source = create_v2(cli, monkeypatch)
        identity = "ses_v2"
        sql = "UPDATE session_message SET data = ? WHERE type = 'assistant'"
    else:
        cli, identity = desktop(tmp_path, monkeypatch, "minimax")
        sql = (
            "UPDATE local_runtime_sessions SET extra_data_json = ?"
            if provider == "minimax-metadata"
            else "UPDATE local_runtime_message_rows SET data_json = ? WHERE msg_id = 'assistant-1'"
        )
    with sqlite3.connect(cli.source) as connection:
        connection.execute(sql, (raw,))
    fails(cli, f"{'opencode' if provider == 'opencode' else 'minimax'}://{identity}")
