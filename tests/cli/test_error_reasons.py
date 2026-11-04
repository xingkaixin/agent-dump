"""Read and export failures keep their reason, exit code and source isolation."""

import sqlite3

from sqlite_fixture import create_legacy


def test_unsafe_export_identity_has_complete_capability_diagnostic(cli):
    identity = ".."
    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session SET id = ?", (identity,))
        connection.execute("UPDATE message SET session_id = ?", (identity,))
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(f"opencode://{identity}", "--format", "json,md,raw", "--output", "exports", "--lang", "en")
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
