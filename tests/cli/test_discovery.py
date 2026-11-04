"""Shared discovery behavior, diagnostics and failure isolation."""

import os
from pathlib import Path
import shutil

from cli_fixture import write_jsonl
import pytest


@pytest.mark.parametrize(
    ("scope", "code", "summary"),
    [
        (None, 1, "No usable local session data found."),
        ("codex", 0, "No usable provider within the query scope."),
    ],
)
def test_no_sources_diagnostic_and_exit_code(cli, scope, code, summary):
    shutil.rmtree(cli.root / "sources")
    args = ["--list", "--lang", "en"]
    if scope:
        args.extend(["-q", f"provider:{scope}"])
    result = cli.run(*args)
    assert result.returncode == code, result.stdout + result.stderr
    assert not result.stderr
    assert f"Diagnostic\nSummary: {summary}\n" in result.stdout
    assert not (cli.root / "sources").exists()


def test_corrupt_database_is_isolated(cli):
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"broken synthetic database")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("--list", "-d", "36500", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "codex://" in result.stdout
    assert result.stderr == "⚠️  OpenCode provider operation failed: DatabaseError: file is not a database\n"
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="Windows forbids control characters in filenames")
def test_bad_file_keeps_good_sessions_and_warning_is_one_line(cli):
    bad = cli.source.parent / "rollout-bad\n\x1b[31m.jsonl"
    write_jsonl(bad, [{"type": "session_meta", "payload": 42}])
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("--list", "-d", "36500", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "codex://" in result.stdout and "opencode://" in result.stdout
    assert len(result.stderr.splitlines()) == 1
    assert "\x1b" not in result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before
