"""Read and export failures keep their reason, exit code and source isolation."""

import sqlite3

from cli_fixture import IDENTITY
import pytest
from sqlite_fixture import create_legacy, create_v2


@pytest.mark.parametrize("identity", ["..", "/", "folder/.."])
def test_unsafe_export_identity_has_complete_capability_diagnostic(cli, identity):
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session SET id = ?", (identity,))
        connection.execute("UPDATE message SET session_id = ?", (identity,))
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"opencode://{identity}", "--format", "json,md,raw", "--output", "exports", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    diagnostic = (
        "Diagnostic\nSummary: session id cannot be used as an export filename\n"
        f"Details:\n  - session id: '{identity}'\n  - reason: no usable filename component\n"
        "Capability gap: session id does not produce a safe filename\n"
    )
    assert result.stdout.count(diagnostic) == 3
    assert not list((cli.root / "exports").rglob("*.*"))
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("{broken", "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"),
        ("[]", "message data must be an object"),
        ('"text"', "message data must be an object"),
    ],
)
def test_opencode_v2_bad_data_fails_each_requested_format(cli, monkeypatch, lang, raw, reason):
    path = create_v2(cli, monkeypatch)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session_message SET data = ? WHERE type = 'assistant'", (raw,))
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(
        "rust", "opencode://ses_v2", "--format", "print,json,md,raw", "--output", "exports", "--lang", lang
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.count(f"  - Invalid OpenCode V2 message msg_2: {reason}\n") == 4
    assert not list((cli.root / "exports").rglob("*.*"))
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("obstacle", ["destination", "provider-directory", "parent-directory"])
def test_export_filesystem_errors_keep_obstacles_and_partial_success(cli, obstacle):
    output = cli.root / "exports"
    blocked = output / "codex" / f"{IDENTITY}.json"
    if obstacle == "destination":
        blocked.mkdir(parents=True)
    elif obstacle == "provider-directory":
        output.mkdir()
        (output / "codex").write_text("obstacle")
    else:
        output.write_text("obstacle")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json,md,raw", "--output", "exports", "--lang", "en")
    assert not result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before
    if obstacle == "destination":
        assert result.returncode == 0, result.stdout
        assert result.stdout.count("Diagnostic\n") == 1
        assert blocked.is_dir() and not list(blocked.iterdir())
        assert sorted(path.name for path in (output / "codex").iterdir() if path.is_file()) == [
            f"{IDENTITY}.md",
            f"{IDENTITY}.raw.jsonl",
        ]
        assert not list((output / "codex").glob(".*.tmp"))
    else:
        assert result.returncode == 1, result.stdout
        assert result.stdout.count("Diagnostic\n") == 3
        obstacle_file = output / "codex" if obstacle == "provider-directory" else output
        assert obstacle_file.read_text() == "obstacle"
