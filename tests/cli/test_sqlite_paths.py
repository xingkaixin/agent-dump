"""Database selection, bound identifiers and failure isolation through the CLI."""

import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest
from sqlite_fixture import create_legacy


@pytest.mark.parametrize("location", ["absolute", "relative", "xdg", "home", "fallback"])
def test_opencode_database_selection(cli, location):
    source = create_legacy(cli)
    cli.environment.pop("OPENCODE_DB")
    if location == "absolute":
        target = source.with_name("session #库.db" if os.name == "nt" else "session #?库.db")
        cli.environment["OPENCODE_DB"] = str(target)
    elif location in ("relative", "xdg"):
        root = cli.root / "sources/data-home"
        cli.environment["XDG_DATA_HOME"] = str(root)
        target = (
            root
            / "opencode"
            / (("channel #.db" if os.name == "nt" else "channel #?.db") if location == "relative" else "opencode.db")
        )
        if location == "relative":
            cli.environment["OPENCODE_DB"] = target.name
    elif location == "home":
        cli.environment.pop("XDG_DATA_HOME")
        target = Path(cli.environment["HOME"]) / ".local/share/opencode/opencode.db"
    else:
        target = cli.root / "data/opencode/opencode.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), target)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "opencode://ses_old", "--head", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "- Title: Legacy 会话" in result.stdout
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("explicit", ["missing.db", ":memory:"])
def test_explicit_unavailable_database_never_falls_back_or_creates_files(cli, explicit):
    create_legacy(cli, path=cli.root / "data/opencode/opencode.db")
    target = Path(cli.environment["XDG_DATA_HOME"]) / "opencode" / explicit
    cli.environment["OPENCODE_DB"] = explicit
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "opencode://ses_old", "--head", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.startswith("Diagnostic\nSummary: No matching session found.\n")
    assert not target.exists()
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("identity", ["id' OR 1=1 --", "nested/session", "会话 #?"])
def test_session_identifiers_are_bound_parameters(cli, identity):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session SET id = ?", (identity,))
        connection.execute("UPDATE message SET session_id = ?", (identity,))
    head = cli.run("rust", f"opencode://{identity}", "--head", "--lang", "en")
    assert head.returncode == 0, head.stdout + head.stderr
    assert f"- URI: opencode://{identity}\n" in head.stdout
    result = cli.run("rust", f"opencode://{identity}", "--format", "json,raw", "--output", "exports", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    files = [path for path in (cli.root / "exports").rglob("*") if path.is_file()]
    assert {path.parent for path in files} == {cli.root / "exports/opencode"}
    assert sorted(path.name.split(".", 1)[1] for path in files) == ["json", "raw.json"]
    exported = json.loads(
        next(path for path in files if path.name.endswith(".json") and ".raw." not in path.name).read_text()
    )
    assert exported["id"] == identity


def test_unknown_schema_is_an_error_not_an_empty_export(cli):
    path = cli.root / "sources/unknown.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE other (value TEXT)")
    cli.environment["OPENCODE_DB"] = str(path)
    before = path.read_bytes()
    result = cli.run("rust", "opencode://missing", "--format", "json,raw", "--output", "exports", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == "⚠️  OpenCode session lookup failed: no such table: session\n"
    assert path.read_bytes() == before
    assert not any(item.is_file() for item in (cli.root / "exports").rglob("*"))
