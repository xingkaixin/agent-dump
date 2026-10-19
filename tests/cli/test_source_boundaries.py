"""Source locks, permissions and default homes use only isolated fixtures."""

import os
import shutil
import sqlite3

from cli_fixture import IDENTITY, make_cli
from desktop_fixture import desktop
import pytest
from sqlite_fixture import create_v2
from test_title_cache import sessions


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


@pytest.mark.parametrize(("provider", "name"), [("opencode", "OpenCode"), ("deepchat", "DeepChat")])
def test_exclusive_database_lock_fails_without_source_writes(tmp_path, monkeypatch, provider, name):
    if provider == "opencode":
        cli = make_cli(tmp_path, monkeypatch)
        cli.source = create_v2(cli, monkeypatch)
        identity = "ses_v2"
    else:
        cli, identity = desktop(tmp_path, monkeypatch, provider)
    before = cli.fixtures.source_manifest(cli.root)
    with sqlite3.connect(cli.source) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        # Reading the manifest here would release this process's POSIX SQLite lock.
        result = cli.run(f"{provider}://{identity}", "--head", "--lang", "en")
        writer.rollback()
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == f"⚠️  {name} session lookup failed: database is locked\n"
    assert result.stdout.startswith("Diagnostic\nSummary: No matching session found.\n")
    assert cli.fixtures.source_manifest(cli.root) == before
    unlocked = cli.run(f"{provider}://{identity}", "--head", "--lang", "en")
    assert unlocked.returncode == 0, unlocked.stdout + unlocked.stderr
    assert f"- URI: {provider}://{identity}" in unlocked.stdout


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX source permissions")
def test_unreadable_title_index_recovers_without_source_writes(cli):
    index = sessions(cli, "claude")
    index.write_text("{}")
    before = cli.fixtures.source_manifest(cli.root)
    index.chmod(0)
    try:
        result = cli.run(f"claude://{IDENTITY}", "--head", "--lang", "en")
    finally:
        index.chmod(0o600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == f"⚠️  Failed to load title cache: [Errno 13] Permission denied: '{index}'\n"
    assert "- Title: Keep" in result.stdout
    assert cli.fixtures.source_manifest(cli.root) == before
