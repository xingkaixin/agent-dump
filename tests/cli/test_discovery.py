"""Shared discovery behavior, diagnostics and failure isolation."""

import importlib
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from cli_fixture import IDENTITY, ROOT, write_jsonl
from desktop_fixture import NOW, PROVIDERS, desktop
import pytest
from sqlite_fixture import create_legacy
from test_antigravity_cli import create as create_antigravity, user
from test_claude import create as create_claude, event
from test_cursor import cursor
from test_droid import create as create_droid, message as droid_message
from test_dsh import create as create_dsh, header as dsh_header, user as dsh_user
from test_gemini_cli import create as create_gemini_cli, entry, header as gemini_header
from test_grok import create as create_grok, summary as grok_summary, user as grok_user
from test_kimi import create as create_kimi
from test_kimi_code import appended, create as create_kimi_code
from test_omp import create as create_omp
from test_pi import create as create_pi, message
from test_qoder import create as create_qoder


def test_all_registered_providers_together(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    create_claude(cli, [event("user", "Claude")])
    create_kimi(cli, context=[{"role": "user", "content": "Kimi"}])
    create_kimi_code(cli, [appended("user", "Kimi-Code")], state={})
    create_droid(cli, [droid_message("user", "Droid")], start={})
    create_grok(cli, [grok_user("Grok")], summary=grok_summary())
    create_pi(cli, [message("user", "Pi")])
    create_qoder(cli.root / "sources/qoder", [event("user", "Qoder")])
    create_qoder(cli.root / "sources/qoder-cn", [event("user", "Qoder CN")])
    create_omp(Path(cli.environment["HOME"]) / ".omp/agent/sessions", IDENTITY, [message("user", "oh-my-pi")])
    create_gemini_cli(cli, [gemini_header(), entry("u", "user", "Gemini CLI")])
    create_dsh(cli, [dsh_header(), dsh_user(0, "DSH")])
    create_antigravity(cli, [user("Antigravity CLI")])
    monkeypatch.syspath_prepend(str(ROOT / "tests" / "cli"))
    for provider, (variable, suffix, _) in PROVIDERS.items():
        module = importlib.import_module(f"{provider}_fixtures")
        getattr(module, f"create_{provider}_db")(Path(cli.environment[variable]) / suffix, NOW)
    if sys.platform == "darwin" or os.name == "nt":
        create_legacy(cli, "zcode", path=Path(cli.environment["HOME"]) / ".zcode/cli/db/db.sqlite")
    result = cli.run("rust", "--list", "-d", "36500")
    expected = [
        "OpenCode",
        "Codex",
        "Kimi",
        "Kimi-Code",
        "Claude Code",
        "Qoder",
        "Qoder CN",
        "Cursor",
        "Droid",
        "Grok",
        "Pi",
        "oh-my-pi",
        "Gemini CLI",
        "DSH",
        "DeepChat",
        "Cherry Studio",
        "MiniMax Code",
        "Antigravity CLI",
    ]
    if sys.platform == "darwin" or os.name == "nt":
        expected.insert(1, "ZCode")
    assert [line.split(" (")[0][2:] for line in result.stdout.splitlines() if line.startswith("📁 ")] == expected


@pytest.mark.parametrize(
    ("scope", "code", "summary"),
    [
        (None, 1, "No usable local session data found."),
        ("codex", 0, "No usable provider within the query scope."),
        ("pi,codex", 0, "No usable provider within the query scope."),
    ],
)
def test_no_sources_diagnostic_and_exit_code(cli, scope, code, summary):
    shutil.rmtree(cli.root / "sources")
    args = ["--list", "--lang", "en"]
    if scope:
        args.extend(["-q", f"provider:{scope}"])
    result = cli.run("rust", *args)
    assert result.returncode == code, result.stdout + result.stderr
    assert not result.stderr
    assert f"Diagnostic\nSummary: {summary}\n" in result.stdout
    assert not (cli.root / "sources").exists()


@pytest.mark.parametrize("scope", [None, "opencode"])
def test_corrupt_database_isolated_and_explicit_scope_skips_it(cli, scope):
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"broken synthetic database")
    before = cli.fixtures.source_manifest(cli.root)
    args = ["--list", "-d", "36500", "--lang", "en"]
    if scope:
        args.extend(["-q", f"provider:{scope}"])
    result = cli.run("rust", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ("codex://" in result.stdout) == (scope != "opencode")
    assert result.stderr == "⚠️  OpenCode provider operation failed: DatabaseError: file is not a database\n"
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="Windows forbids control characters in filenames")
def test_bad_file_keeps_good_sessions_and_warning_is_one_line(cli):
    bad = cli.source.parent / "rollout-bad\n\x1b[31m.jsonl"
    write_jsonl(bad, [{"type": "session_meta", "payload": 42}])
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "--list", "-d", "36500", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "codex://" in result.stdout and "opencode://" in result.stdout
    assert len(result.stderr.splitlines()) == 1
    assert "\x1b" not in result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before


def test_claude_projects_file_is_a_source_failure(cli):
    source = cli.root / "sources/claude/projects"
    source.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.rmtree(source)
    source.write_text("not a project directory")
    before = cli.fixtures.source_manifest(cli.root)
    for args, exit_code, prefix in [
        (("--list", "-q", "provider:claude", "-d", "36500"), 0, "⚠️  Claude Code provider operation failed: "),
        (("claude://missing", "--head"), 1, "⚠️  Claude Code session lookup failed: "),
    ]:
        result = cli.run("rust", *args, "--lang", "en")
        assert result.returncode == exit_code, result.stdout + result.stderr
        assert len(result.stderr.splitlines()) == 1
        assert result.stderr.startswith(prefix)
        assert str(source) in result.stderr or "directory" in result.stderr.lower()
        assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize(
    ("provider", "warning"),
    [
        (
            "cherry",
            "Failed to read Cherry Studio session topic-contract: Invalid Cherry Studio active branch: contract",
        ),
        (
            "minimax",
            "Failed to read MiniMax Code session minimax-contract: MiniMax Code session storage is unsupported",
        ),
    ],
)
def test_partial_desktop_failure_keeps_other_providers(tmp_path, monkeypatch, provider, warning):
    cli, _ = desktop(tmp_path, monkeypatch, provider)
    with sqlite3.connect(cli.source) as connection:
        connection.execute(
            "UPDATE topic SET active_node_id = 'absent'"
            if provider == "cherry"
            else "UPDATE local_runtime_sessions SET columnar_version = 2"
        )
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "--list", "-d", "36500", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "codex://" in result.stdout and "opencode://" in result.stdout
    assert result.stderr.startswith(warning)
    assert len(result.stderr.splitlines()) == 1
    assert cli.fixtures.source_manifest(cli.root) == before


def test_all_available_sources_failing_returns_one(cli):
    shutil.rmtree(cli.root / "sources/codex")
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"broken synthetic database")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "--list", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Diagnostic\nSummary: No usable local session data found.\n" in result.stdout
    assert result.stderr == "⚠️  OpenCode provider operation failed: DatabaseError: file is not a database\n"
    assert cli.fixtures.source_manifest(cli.root) == before


def test_provider_initialization_failure_is_isolated(cli):
    cli.environment.pop("CHERRY_STUDIO_USER_DATA_DIR")
    boot = Path(cli.environment["HOME"]) / ".cherrystudio/boot-config.json"
    boot.parent.mkdir()
    boot.write_text("broken synthetic config")
    result = cli.run("rust", "--list", "-d", "36500", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "codex://" in result.stdout
    assert result.stderr.startswith("⚠️  Cherry Studio provider operation failed: JSONDecodeError: ")
    assert boot.read_text() == "broken synthetic config"
