"""Source locks, permissions and long references use only isolated fixtures."""

import os
import sqlite3

from cli_fixture import IDENTITY, make_cli
from desktop_fixture import NOW, desktop
import pytest
from sqlite_fixture import create_v2
from test_cursor import cursor, export as cursor_export, put
from test_title_cache import sessions


@pytest.mark.parametrize("provider", ["opencode", "deepchat"])
def test_exclusive_database_lock_retains_reference_failure(tmp_path, monkeypatch, provider):
    if provider == "opencode":
        cli = make_cli(tmp_path, monkeypatch)
        cli.source = create_v2(cli, monkeypatch)
        identity = "ses_v2"
    else:
        cli, identity = desktop(tmp_path, monkeypatch, provider)
    before = cli.fixtures.source_manifest(cli.root)
    results = []
    with sqlite3.connect(cli.source) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        # Reading the manifest here would release this process's POSIX SQLite lock.
        for candidate in ("python", "rust"):
            result = cli.run(candidate, f"{provider}://{identity}", "--head", "--lang", "en")
            assert result.returncode == 1, result.stdout + result.stderr
            assert "database is locked" in result.stderr
            results.append((result.stdout, result.stderr))
        writer.rollback()
    assert results[0] == results[1], results
    assert cli.fixtures.source_manifest(cli.root) == before
    cli.parity(f"{provider}://{identity}", "--head", "--lang", "en")


@pytest.mark.skipif(os.name == "nt", reason="POSIX source permissions")
@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_unreadable_title_index_recovers_without_source_writes(cli, provider):
    index = sessions(cli, provider)
    index.write_text("{}")
    before = cli.fixtures.source_manifest(cli.root)
    index.chmod(0)
    try:
        results = [
            cli.run(candidate, f"{provider}://{IDENTITY}", "--head", "--lang", "en") for candidate in ("python", "rust")
        ]
        assert all(result.returncode == 0 for result in results)
        assert "Permission denied" in results[0].stderr
        assert (results[0].stdout, results[0].stderr) == (results[1].stdout, results[1].stderr)
    finally:
        index.chmod(0o600)
    assert cli.fixtures.source_manifest(cli.root) == before
    cli.parity(f"{provider}://{IDENTITY}", "--head", "--lang", "en")


def test_cursor_long_subagent_chain_preserves_completion(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    parent = "parent"
    for index in range(128):
        child = f"child-{index}"
        put(
            cli,
            f"composerData:{child}",
            {"name": child, "createdAt": NOW, "subagentInfo": {"parentComposerId": parent}},
        )
        put(
            cli,
            f"bubbleId:{parent}:c-task",
            {"type": 2, "toolFormerData": {"name": "agent", "additionalData": {"subagentComposerId": child}}},
        )
        put(cli, f"bubbleId:{child}:a-answer", {"type": 2, "text": f"Completed {index}"})
        parent = child
    cursor_export(cli)
