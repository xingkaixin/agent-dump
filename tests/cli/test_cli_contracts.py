"""Core CLI export, help and source-protection contracts on synthetic sources."""

import os

from cli_fixture import IDENTITY
import pytest


def test_missing_session_and_source_protection(cli):
    assert cli.run("codex://missing", "--head").returncode == 1
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(f"codex://{IDENTITY}", "--format", "json", "--output", str(cli.root / "sources" / "codex"))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires privileges on Windows")
def test_export_symlink_cannot_modify_provider(cli):
    output = cli.root / "exports" / "codex"
    output.mkdir(parents=True)
    (output / f"{IDENTITY}.json").symlink_to(cli.source)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(f"codex://{IDENTITY}", "--format", "json", "--output", str(output.parent))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before
