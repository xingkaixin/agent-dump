"""Source locks, permissions and default homes use only isolated fixtures."""

import os
import shutil
import sqlite3

from cli_fixture import IDENTITY
from sqlite_fixture import create_v2


def test_default_home_uses_the_platform_environment(cli):
    selected = cli.root / "sources/platform-home"
    ignored = cli.root / "sources/ignored-home"
    shutil.copytree(cli.root / "sources/codex", selected / ".codex")
    cli.environment.pop("CODEX_HOME")
    cli.environment.update(
        HOME=str(ignored if os.name == "nt" else selected),
        USERPROFILE=str(selected if os.name == "nt" else ignored),
    )
    result = cli.run(f"codex://{IDENTITY}", "--head", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"- URI: codex://{IDENTITY}" in result.stdout
    assert not ignored.exists()


def test_exclusive_database_lock_fails_without_source_writes(cli, monkeypatch):
    cli.source = create_v2(cli, monkeypatch)
    before = cli.fixtures.source_manifest(cli.root)
    with sqlite3.connect(cli.source) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        # Reading the manifest here would release this process's POSIX SQLite lock.
        result = cli.run("opencode://ses_v2", "--head", "--lang", "en")
        writer.rollback()
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == "⚠️  OpenCode session lookup failed: database is locked\n"
    assert result.stdout.startswith("Diagnostic\nSummary: No matching session found.\n")
    assert cli.fixtures.source_manifest(cli.root) == before
    unlocked = cli.run("opencode://ses_v2", "--head", "--lang", "en")
    assert unlocked.returncode == 0, unlocked.stdout + unlocked.stderr
    assert "- URI: opencode://ses_v2" in unlocked.stdout
