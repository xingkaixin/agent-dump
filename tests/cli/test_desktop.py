import sqlite3

from desktop_fixture import desktop
import pytest

NAMES = {"deepchat": "DeepChat", "cherry": "Cherry Studio", "minimax": "MiniMax Code"}


@pytest.mark.parametrize(
    "provider,sql",
    [
        ("deepchat", "DROP TABLE deepchat_messages"),
        ("cherry", "DROP TABLE agent_workspace"),
        ("minimax", "ALTER TABLE local_runtime_sessions DROP COLUMN columnar_version"),
        ("minimax", "ALTER TABLE local_runtime_message_rows DROP COLUMN data_json"),
        ("minimax", "DROP TABLE local_runtime_messages"),
        ("minimax", "DROP TABLE local_runtime_message_row_migrations"),
    ],
)
def test_unknown_schema_is_not_exported(tmp_path, monkeypatch, provider, sql):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    with sqlite3.connect(cli.source) as connection:
        connection.execute(sql)
    reason = f"This database does not contain the supported {NAMES[provider]} session tables"
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(f"{provider}://{identity}", "--format", "json,md,print", "--output", "exports", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr.startswith(f"⚠️  {NAMES[provider]} session lookup failed: {reason}")
    listing = cli.run("--list", "-d", "36500", "-q", f"provider:{provider}", "--lang", "en")
    assert listing.returncode == 0, listing.stdout + listing.stderr
    assert listing.stderr.startswith(
        f"⚠️  {NAMES[provider]} provider operation failed: DiagnosticCapabilityError: {reason}"
    )
    assert not (cli.root / "exports").exists()
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize(
    "provider,sql,reason",
    [
        (
            "cherry",
            "UPDATE agent_session_message SET data = 'invalid' WHERE role = 'assistant'",
            "Invalid Cherry Studio message: b-assistant",
        ),
        (
            "minimax",
            "UPDATE local_runtime_message_rows SET data_json = 'invalid'",
            "Expecting value: line 1 column 1 (char 0)",
        ),
    ],
)
def test_bad_body_remains_head_readable_and_fails_export(tmp_path, monkeypatch, provider, sql, reason):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    with sqlite3.connect(cli.source) as connection:
        connection.execute(sql)
    before = cli.fixtures.source_manifest(cli.root)
    head = cli.run(f"{provider}://{identity}", "--head", "--lang", "en")
    assert head.returncode == 0, head.stdout + head.stderr
    assert f"- URI: {provider}://{identity}" in head.stdout
    result = cli.run(f"{provider}://{identity}", "--format", "json,md,print", "--output", "exports", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.count(f"Summary: Failed to read session data.\nDetails:\n  - {reason}\n") == 3
    assert not [path for path in (cli.root / "exports").rglob("*") if path.is_file()]
    assert cli.fixtures.source_manifest(cli.root) == before
