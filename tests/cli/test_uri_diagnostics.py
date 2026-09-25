"""URI failure contracts, including diagnostic channels and source isolation."""

from pathlib import Path
import shutil
import sqlite3

from cli_fixture import IDENTITY, header, message, write_jsonl
from desktop_fixture import desktop
import pytest
from sqlite_fixture import create_v2
from test_cursor import cursor


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "uri",
    [
        "invalid",
        "https://session",
        "Codex://id",
        "codex://",
        "codex://threads/",
        "codex://\n",
        "codex://id\nforged",
        "claudecode://id",
        " codex://id",
        "bad://\x1b[2K\rforged\u202e",
    ],
)
def test_invalid_uri_diagnostic_is_exact_and_safe(cli, lang, uri):
    cli.parity(uri, "--lang", lang, exit_code=1)
    result = cli.run("rust", uri, "--lang", lang)
    assert not result.stderr
    assert "\x1b" not in result.stdout and "\r" not in result.stdout and "\u202e" not in result.stdout


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "scheme", ["opencode", "zcode", "codex", "kimi", "claude", "cursor", "pi", "deepchat", "cherry", "minimax"]
)
def test_missing_session_and_missing_provider_share_diagnostic(cli, lang, scheme):
    cli.parity(f"{scheme}://missing", "--head", "--lang", lang, exit_code=1)
    shutil.rmtree(cli.root / "sources")
    cli.parity(f"{scheme}://missing", "--head", "--lang", lang, exit_code=1)
    assert not (cli.root / "sources").exists()


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "identity", ["threads/missing", "missing\n", "not-found\r\x1b[2K\u202e", "not-found-" + "字" * 600]
)
def test_missing_uri_preserves_parsed_evidence_without_terminal_controls(cli, lang, identity):
    cli.parity(f"codex://{identity}", "--lang", lang, exit_code=1)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("formats", ["raw", "md", "raw,md,json,raw"])
def test_cursor_format_rejection_lists_all_unsupported_formats(tmp_path, monkeypatch, lang, formats):
    cli = cursor(tmp_path, monkeypatch)
    cli.parity("cursor://request-parent", "--format", formats, "--lang", lang, exit_code=1)
    assert not (cli.root / "exports").exists()


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
def test_desktop_format_rejection_precedes_any_export(tmp_path, monkeypatch, provider, lang):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    cli.parity(
        f"{provider}://{identity}", "--format", "json,raw,print", "--output", "exports", "--lang", lang, exit_code=1
    )
    assert not (cli.root / "exports").exists()


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("formats", ["json", "invalid", ""])
def test_head_format_conflict_precedes_lookup_and_format_validation(cli, lang, formats):
    cli.parity("codex://missing", "--head", "--format", formats, "--lang", lang, exit_code=1)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_head_ignores_output_without_creating_directories(cli, lang):
    cli.parity(f"codex://{IDENTITY}", "--head", "--output", "exports", "--lang", lang)
    assert not (cli.root / "exports").exists()


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("formats", ["", "json,", "xml", "raw,,json"])
def test_invalid_format_list_is_an_argument_error(cli, lang, formats):
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "codex://missing", "--format", formats, "--lang", lang)
        assert result.returncode == 2
        assert not result.stdout and result.stderr


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_lookup_failure_warns_then_prints_missing_session(cli, lang):
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"broken synthetic database")
    cli.parity("opencode://missing", "--lang", lang, exit_code=1)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_recovered_lookup_warning_does_not_hide_matching_session(cli, lang):
    bad = cli.source.parent / f"bad-{IDENTITY}.jsonl"
    write_jsonl(bad, [{"type": "session_meta", "payload": 42}])
    cli.write([header(), message("user", "Retained")])
    cli.source.rename(cli.source.with_name("fallback.jsonl"))
    before = cli.fixtures.source_manifest(cli.root)
    results = [cli.run(candidate, f"codex://{IDENTITY}", "--head", "--lang", lang) for candidate in ("python", "rust")]
    assert results[0].stdout == results[1].stdout
    assert all(result.returncode == 0 for result in results)
    assert all(len(result.stderr.splitlines()) == 2 for result in results)
    assert results[0].stderr.split("bad-", 1)[0] == results[1].stderr.split("bad-", 1)[0]
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_fallback_lookup_chooses_newest_matching_session(cli, lang):
    cli.write([header(cwd="/older"), message("user", "Older")])
    cli.source.rename(cli.source.with_name("older.jsonl"))
    write_jsonl(cli.source.with_name("newer.jsonl"), [header(cwd="/newest", timestamp="2026-02-01T00:00:00Z")])
    cli.parity(f"codex://{IDENTITY}", "--head", "--lang", lang)
    assert str(Path("/newest")) in cli.run("rust", f"codex://{IDENTITY}", "--head").stdout


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_read_failure_has_diagnostic_per_requested_format(cli, monkeypatch, lang):
    database = create_v2(cli, monkeypatch)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE session_message SET data = '{broken'")
    before = cli.fixtures.source_manifest(cli.root)
    results = [
        cli.run(candidate, "opencode://ses_v2", "--format", "print,json,md,raw", "--output", "exports", "--lang", lang)
        for candidate in ("python", "rust")
    ]
    for result in results:
        assert result.returncode == 1
        assert not result.stderr
        assert not list((cli.root / "exports").rglob("*.*"))
    python_lines = results[0].stdout.splitlines()
    rust_lines = results[1].stdout.splitlines()
    assert python_lines[0:2] == rust_lines[0:2]
    assert rust_lines.count(python_lines[0]) == python_lines.count(python_lines[0]) == 4
    assert cli.fixtures.source_manifest(cli.root) == before
