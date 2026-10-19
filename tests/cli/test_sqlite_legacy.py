"""Legacy OpenCode read-only database contracts."""

import json
import sqlite3

import pytest
from sqlite_fixture import create_legacy


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_database_and_wal_remain_unchanged_and_new_commits_are_visible(cli, journal):
    path = create_legacy(cli)
    writer = sqlite3.connect(path)
    try:
        writer.execute(f"PRAGMA journal_mode={journal}")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        for body in ("Initial commit", "Committed update"):
            writer.execute(
                "UPDATE part SET data = ? WHERE id = 'part_0'", (json.dumps({"type": "text", "text": body}),)
            )
            writer.commit()
            files = sorted(path.parent.iterdir())
            durable = {item: item.read_bytes() for item in files if not item.name.endswith("-shm")}
            result = cli.run("rust", "opencode://ses_old", "--format", "json", "--output", "exports", "--lang", "en")
            assert result.returncode == 0, result.stdout + result.stderr
            data = json.loads((cli.root / "exports/opencode/ses_old.json").read_text())
            assert data["messages"][0]["parts"][0]["text"] == body
            assert sorted(path.parent.iterdir()) == files
            assert all(item.read_bytes() == content for item, content in durable.items())
    finally:
        writer.close()


def test_exports_cannot_write_inside_database_source(cli):
    path = create_legacy(cli)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "opencode://ses_old", "--format", "json,md,raw", "--output", str(path.parent))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before
