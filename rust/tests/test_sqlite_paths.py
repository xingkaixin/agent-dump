"""Database selection, bound identifiers and failure isolation through the CLI."""

import json
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
        target = source.with_name("session #?库.db")
        cli.environment["OPENCODE_DB"] = str(target)
    elif location in ("relative", "xdg"):
        root = cli.root / "sources/data-home"
        cli.environment["XDG_DATA_HOME"] = str(root)
        target = root / "opencode" / ("channel #?.db" if location == "relative" else "opencode.db")
        if location == "relative":
            cli.environment["OPENCODE_DB"] = target.name
    elif location == "home":
        cli.environment.pop("XDG_DATA_HOME")
        target = Path(cli.environment["HOME"]) / ".local/share/opencode/opencode.db"
    else:
        target = cli.root / "data/opencode/opencode.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), target)
    cli.parity("opencode://ses_old", "--head", "--lang", "en")
    cli.parity("opencode://ses_old", "--format", "json", "--output", "exports", "--lang", "en", json_export=True)


@pytest.mark.parametrize("explicit", ["missing.db", ":memory:"])
def test_explicit_unavailable_database_never_falls_back_or_creates_files(cli, explicit):
    create_legacy(cli, path=cli.root / "data/opencode/opencode.db")
    target = Path(cli.environment["XDG_DATA_HOME"]) / "opencode" / explicit
    cli.environment["OPENCODE_DB"] = explicit
    before = cli.fixtures.source_manifest(cli.root)
    for candidate in ("python", "rust"):
        assert cli.run(candidate, "opencode://ses_old", "--head").returncode == 1
        assert not target.exists()
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("identity", ["id' OR 1=1 --", "nested/session", "会话 #?"])
def test_session_identifiers_are_bound_parameters(cli, identity):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session SET id = ?", (identity,))
        connection.execute("UPDATE message SET session_id = ?", (identity,))
    cli.parity(f"opencode://{identity}", "--head", "--lang", "en")
    cli.parity(
        f"opencode://{identity}",
        "--format",
        "json,raw",
        "--output",
        "exports",
        "--lang",
        "en",
        formats=("json", "raw-json"),
    )


@pytest.mark.parametrize("invalid", [None, "[]", "{broken"])
def test_legacy_bad_records_warn_and_keep_healthy_messages(cli, invalid):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE message SET data = ? WHERE id = 'msg_developer'", (invalid,))
        connection.execute("UPDATE part SET data = ? WHERE id = 'part_1'", (invalid,))
    before = cli.fixtures.source_manifest(cli.root)
    results = []
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "opencode://ses_old", "--format", "json,raw", "--output", "exports", "--lang", "en")
        assert result.returncode == 0
        assert result.stderr
        outputs = {item.name: json.loads(item.read_text()) for item in (cli.root / "exports/opencode").glob("*.json")}
        assert outputs["ses_old.json"]["stats"]["message_count"] == 2
        results.append(outputs)
        assert cli.fixtures.source_manifest(cli.root) == before
    assert results[0] == results[1]


def test_unknown_schema_is_an_error_not_an_empty_export(cli):
    path = cli.root / "sources/unknown.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE other (value TEXT)")
    cli.environment["OPENCODE_DB"] = str(path)
    before = path.read_bytes()
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "opencode://missing", "--format", "json,raw", "--output", "exports")
        assert result.returncode == 1
        assert path.read_bytes() == before
        assert not any(item.is_file() for item in (cli.root / "exports").rglob("*"))
