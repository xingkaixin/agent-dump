import sqlite3

from desktop_fixture import desktop, exports, fails
import pytest


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_desktop_list_head_and_exports(tmp_path, monkeypatch, provider, lang):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    cli.parity("--list", "-d", "36500", "-q", f"provider:{provider}", "--lang", lang)
    cli.parity(f"{provider}://{identity}", "--head", "--lang", lang)
    data = exports(cli, provider, identity, lang)
    assert len(data["messages"]) == 2


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
@pytest.mark.parametrize("formats", ["raw", "json,raw", "print,raw"])
def test_unsupported_raw_rejects_whole_request(tmp_path, monkeypatch, provider, formats):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    fails(cli, f"{provider}://{identity}", formats)


@pytest.mark.parametrize(
    "provider,sql",
    [
        ("deepchat", "DROP TABLE deepchat_messages"),
        ("cherry", "DROP TABLE agent_workspace"),
        ("minimax", "ALTER TABLE local_runtime_sessions DROP COLUMN columnar_version"),
    ],
)
def test_unknown_schema_is_not_exported(tmp_path, monkeypatch, provider, sql):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    with sqlite3.connect(cli.source) as connection:
        connection.execute(sql)
    fails(cli, f"{provider}://{identity}")


@pytest.mark.parametrize(
    "provider,sql",
    [
        ("deepchat", "UPDATE deepchat_messages SET content = 'invalid' WHERE role = 'assistant'"),
        ("cherry", "UPDATE agent_session_message SET data = 'invalid' WHERE role = 'assistant'"),
        ("minimax", "UPDATE local_runtime_message_rows SET data_json = 'invalid'"),
    ],
)
def test_bad_body_remains_head_readable_and_fails_export(tmp_path, monkeypatch, provider, sql):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    with sqlite3.connect(cli.source) as connection:
        if provider == "deepchat":
            connection.execute("DELETE FROM deepchat_assistant_blocks")
        connection.execute(sql)
    cli.parity(f"{provider}://{identity}", "--head", "--lang", "en")
    fails(cli, f"{provider}://{identity}")
