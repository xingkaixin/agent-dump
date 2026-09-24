"""Shared discovery behavior through isolated Python and Rust processes."""

import importlib
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from cli_fixture import ROOT, header, write_jsonl
from desktop_fixture import NOW, PROVIDERS, desktop
import pytest
from sqlite_fixture import create_legacy
from test_claude import create as create_claude, event
from test_cursor import cursor
from test_kimi import create as create_kimi
from test_pi import create as create_pi, message


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("summary", [True, False])
@pytest.mark.parametrize("days", ["1", "36500"])
def test_all_providers_list(cli, lang, summary, days):
    args = ["--list", "-d", days, "--lang", lang]
    if not summary:
        args.append("--no-metadata-summary")
    cli.parity(*args)


@pytest.mark.parametrize(
    "query", ["provider:opencode,codex", "PROVIDER:CODEX,opencode,Codex,", "provider:claude,codex"]
)
def test_provider_scope_normalizes_and_preserves_registration_order(cli, query):
    cli.parity("--list", "-d", "36500", "-q", query)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_all_registered_providers_together(tmp_path, monkeypatch, lang):
    cli = cursor(tmp_path, monkeypatch)
    create_claude(cli, [event("user", "Claude")])
    create_kimi(cli, context=[{"role": "user", "content": "Kimi"}])
    create_pi(cli, [message("user", "Pi")])
    monkeypatch.syspath_prepend(str(ROOT / "tests"))
    for provider, (variable, suffix, _) in PROVIDERS.items():
        module = importlib.import_module(f"{provider}_fixtures")
        getattr(module, f"create_{provider}_db")(Path(cli.environment[variable]) / suffix, NOW)
    if sys.platform == "darwin" or os.name == "nt":
        create_legacy(cli, "zcode", path=Path(cli.environment["HOME"]) / ".zcode/cli/db/db.sqlite")
    cli.parity("--list", "-d", "36500", "--lang", lang)
    result = cli.run("rust", "--list", "-d", "36500")
    expected = ["OpenCode", "Codex", "Kimi", "Claude Code", "Cursor", "Pi", "DeepChat", "Cherry Studio", "MiniMax Code"]
    if sys.platform == "darwin" or os.name == "nt":
        expected.insert(1, "ZCode")
    assert [line.split(" (")[0][2:] for line in result.stdout.splitlines() if line.startswith("📁 ")] == expected


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("scope", [None, "codex", "pi,codex"])
def test_no_sources_diagnostic_and_exit_code(cli, lang, scope):
    shutil.rmtree(cli.root / "sources")
    args = ["--list", "--lang", lang]
    if scope:
        args.extend(["-q", f"provider:{scope}"])
    results = [cli.run(candidate, *args) for candidate in ("python", "rust")]
    assert (results[0].returncode, results[0].stdout, results[0].stderr) == (
        results[1].returncode,
        results[1].stdout,
        results[1].stderr,
    )
    assert results[1].returncode == (0 if scope else 1)
    assert not (cli.root / "sources").exists()


@pytest.mark.parametrize("state", ["missing", "directory", "candidate", "old", "empty-database"])
def test_availability_is_independent_of_filtered_sessions(cli, state):
    shutil.rmtree(cli.root / "sources/codex/sessions")
    if state in {"directory", "candidate", "old"}:
        directory = cli.root / "sources/codex/sessions"
        directory.mkdir()
        if state == "candidate":
            (directory / "empty.jsonl").touch()
        if state == "old":
            write_jsonl(directory / "old.jsonl", [header()])
    if state == "empty-database":
        with sqlite3.connect(cli.environment["OPENCODE_DB"]) as connection:
            connection.execute("DELETE FROM session_v2")
    cli.parity("--list", "-d", "1")
    result = cli.run("rust", "--list", "-d", "1")
    assert ("📁 Codex" in result.stdout) == (state in {"candidate", "old"})
    assert "📁 OpenCode (0 " in result.stdout


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("scope", [None, "codex", "opencode"])
def test_corrupt_database_isolated_and_explicit_scope_skips_it(cli, lang, scope):
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"broken synthetic database")
    before = cli.fixtures.source_manifest(cli.root)
    args = ["--list", "-d", "36500", "--lang", lang]
    if scope:
        args.extend(["-q", f"provider:{scope}"])
    results = [cli.run(candidate, *args) for candidate in ("python", "rust")]
    assert results[0].stdout == results[1].stdout
    for result in results:
        assert result.returncode == 0
        assert ("codex://" in result.stdout) == (scope != "opencode")
        assert ("OpenCode" in result.stderr) == (scope != "codex")
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_bad_file_keeps_good_sessions_and_warning_is_one_line(cli, lang):
    bad = cli.source.parent / "bad\n\x1b[31m.jsonl"
    write_jsonl(bad, [{"type": "session_meta", "payload": 42}])
    before = cli.fixtures.source_manifest(cli.root)
    results = [cli.run(candidate, "--list", "-d", "36500", "--lang", lang) for candidate in ("python", "rust")]
    assert results[0].stdout == results[1].stdout
    assert results[0].stderr.split("bad", 1)[0] == results[1].stderr.split("bad", 1)[0]
    for result in results:
        assert result.returncode == 0
        assert "codex://" in result.stdout and "opencode://" in result.stdout
        assert len(result.stderr.splitlines()) == 1
        assert "\x1b" not in result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("provider", ["cherry", "minimax"])
def test_partial_desktop_failure_keeps_other_providers(tmp_path, monkeypatch, provider):
    cli, _ = desktop(tmp_path, monkeypatch, provider)
    with sqlite3.connect(cli.source) as connection:
        connection.execute(
            "UPDATE topic SET active_node_id = 'absent'"
            if provider == "cherry"
            else "UPDATE local_runtime_sessions SET columnar_version = 2"
        )
    before = cli.fixtures.source_manifest(cli.root)
    results = [cli.run(candidate, "--list", "-d", "36500") for candidate in ("python", "rust")]
    assert results[0].stdout == results[1].stdout
    for result in results:
        assert result.returncode == 0
        assert "codex://" in result.stdout and "opencode://" in result.stdout
        assert result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize(
    "query", ["", "  ", "provider:", "provider:codex keyword", "provider:codex role:user", "keyword"]
)
def test_unsupported_query_never_silently_broadens_scope(cli, query):
    result = cli.run("rust", "--list", "-q", query)
    assert result.returncode != 0
    assert "codex://" not in result.stdout
    assert result.stderr


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_all_available_sources_failing_returns_one(cli, lang):
    shutil.rmtree(cli.root / "sources/codex")
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"broken synthetic database")
    results = [cli.run(candidate, "--list", "--lang", lang) for candidate in ("python", "rust")]
    assert results[0].stdout == results[1].stdout
    for result in results:
        assert result.returncode == 1
        assert result.stderr


@pytest.mark.parametrize("scoped", [False, True])
def test_provider_initialization_failure_is_isolated(cli, scoped):
    cli.environment.pop("CHERRY_STUDIO_USER_DATA_DIR")
    boot = Path(cli.environment["HOME"]) / ".cherrystudio/boot-config.json"
    boot.parent.mkdir()
    boot.write_text("broken synthetic config")
    args = ["--list", "-d", "36500"]
    if scoped:
        args.extend(["-q", "provider:codex"])
    results = [cli.run(candidate, *args) for candidate in ("python", "rust")]
    assert results[0].stdout == results[1].stdout
    for result in results:
        assert result.returncode == 0
        assert "codex://" in result.stdout
        assert bool(result.stderr) == (not scoped)
    assert boot.read_text() == "broken synthetic config"
