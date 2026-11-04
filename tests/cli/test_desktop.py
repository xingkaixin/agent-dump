import sqlite3

from desktop_fixture import desktop


def test_bad_body_remains_head_readable_and_fails_export(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "cherry")
    with sqlite3.connect(cli.source) as connection:
        connection.execute("UPDATE agent_session_message SET data = 'invalid' WHERE role = 'assistant'")
    before = cli.fixtures.source_manifest(cli.root)
    head = cli.run(f"cherry://{identity}", "--head", "--lang", "en")
    assert head.returncode == 0, head.stdout + head.stderr
    assert f"- URI: cherry://{identity}" in head.stdout
    result = cli.run(f"cherry://{identity}", "--format", "json,md,print", "--output", "exports", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    reason = "Invalid Cherry Studio message: b-assistant"
    assert result.stdout.count(f"Summary: Failed to read session data.\nDetails:\n  - {reason}\n") == 3
    assert not [path for path in (cli.root / "exports").rglob("*") if path.is_file()]
    assert cli.fixtures.source_manifest(cli.root) == before
