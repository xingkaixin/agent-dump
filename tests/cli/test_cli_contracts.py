"""Core CLI export, help and source-protection contracts on synthetic sources."""

import hashlib
import json
import os
from pathlib import Path
import shutil

from cli_fixture import IDENTITY, header, message
import pytest


@pytest.mark.parametrize("identity", ["UPPER", "folder/id", "con", "中文", "white space", "a" * 121])
def test_non_portable_export_identity_uses_hashed_filename(cli, identity):
    cli.write([header(identity), message("assistant", "ok")])
    result = cli.run(
        "rust", f"codex://{identity}", "--format", "json", "-output", str(cli.root / "exports"), "--lang", "en"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    name = f"~{hashlib.sha256(identity.encode()).hexdigest()}.json"
    assert [path.relative_to(cli.root) for path in (cli.root / "exports").rglob("*") if path.is_file()] == [
        Path("exports/codex") / name
    ]
    assert json.loads((cli.root / "exports/codex" / name).read_text())["id"] == identity


@pytest.mark.parametrize(
    "args",
    [
        [f"codex://{IDENTITY}", "--format", "xml"],
    ],
)
def test_unsupported_format_fails_explicitly(cli, args):
    result = cli.run("rust", *args)
    assert result.returncode != 0
    assert result.stderr


def test_missing_session_and_source_protection(cli):
    assert cli.run("rust", "codex://missing", "--head").returncode == 1
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json", "--output", str(cli.root / "sources" / "codex"))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


def test_export_cannot_write_inside_another_provider_source(cli):
    cli.environment.pop("OPENCODE_DB")
    projects = cli.root / "sources" / "claude" / "projects"
    projects.mkdir(parents=True, exist_ok=True)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json", "--output", str(projects))
    assert result.returncode == 1
    assert "outside the Provider source directory" in result.stdout + result.stderr
    assert not (projects / "codex").exists()
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires privileges on Windows")
def test_export_symlink_cannot_modify_provider(cli):
    output = cli.root / "exports" / "codex"
    output.mkdir(parents=True)
    (output / f"{IDENTITY}.json").symlink_to(cli.source)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json", "--output", str(output.parent))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("args", [[], ["--help"], ["-h"]])
def test_help_covers_all_operations_in_selected_language(cli, lang, args):
    result = cli.run("rust", f"--lang={lang}", *args)
    assert result.returncode == 0
    assert not result.stderr
    for option in [
        "--shortcut",
        "--collect",
        "--interactive",
        "--search",
        "--config",
        "--providers",
        "-days",
        "-format",
    ]:
        assert option in result.stdout
    assert ("导出 Agent 会话" if lang == "zh" else "Export agent sessions") in result.stdout
    assert "Experimental" not in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions and unprivileged symlinks")
def test_private_export_preserves_existing_directory_permissions(cli):
    output = cli.root / "exports"
    output.mkdir(mode=0o755)
    before_mode = output.stat().st_mode
    args = [f"codex://{IDENTITY}", "--format", "json", "--output", str(output)]
    assert cli.run("rust", *args).returncode == 0
    assert output.stat().st_mode == before_mode
    assert (output / "codex").stat().st_mode & 0o777 == 0o700
    destination = output / "codex" / f"{IDENTITY}.json"
    destination.chmod(0o644)
    assert cli.run("rust", *args).returncode == 0
    assert destination.stat().st_mode & 0o777 == 0o600
    assert list((output / "codex").iterdir()) == [destination]
    shutil.rmtree(output)
    output.symlink_to(cli.root / "sources" / "codex" / "sessions", target_is_directory=True)
    before = cli.fixtures.source_manifest(cli.root)
    assert cli.run("rust", *args).returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before
