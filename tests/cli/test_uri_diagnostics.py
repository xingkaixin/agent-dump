"""URI failure contracts, including diagnostic channels and source isolation."""

from pathlib import Path
import shutil

from cli_fixture import IDENTITY, header, message, write_jsonl
from desktop_fixture import desktop
import pytest

CONTROLS = ("\x1b", "\r", "‮")
NAMES = {"deepchat": "DeepChat", "cherry": "Cherry Studio", "minimax": "MiniMax Code"}


@pytest.mark.parametrize(
    ("uri", "summary", "parsed"),
    [
        ("invalid", "Invalid URI format.", "invalid"),
        ("https://session", "Invalid URI format.", "https://session"),
        ("Codex://id", "Invalid URI format.", "Codex://id"),
        ("codex://", "Invalid URI format.", "codex://"),
        ("codex://threads/", "Invalid URI format.", "codex://threads/"),
        ("codex://\n", "Invalid URI format.", "codex://"),
        ("codex://id\nforged", "Invalid URI format.", "codex://id forged"),
        ("claudecode://id", "Invalid URI format.", "claudecode://id"),
        (" codex://id", "Invalid URI format.", "codex://id"),
        ("bad://\x1b[2K\rforged‮", "Invalid URI format.", "bad:// [2K forged"),
        ("codex://threads/missing", "No matching session found.", "codex://threads/missing"),
        ("codex://missing\n", "No matching session found.", "codex://missing"),
        ("codex://not-found\r\x1b[2K‮", "No matching session found.", "codex://not-found [2K"),
    ],
)
def test_uri_diagnostic_is_exact_and_safe(cli, uri, summary, parsed):
    result = cli.run(uri, "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.splitlines()[:3] == ["Diagnostic", f"Summary: {summary}", f"Parsed URI: {parsed}"]
    assert not any(control in result.stdout for control in CONTROLS)


def test_long_missing_uri_is_truncated_in_diagnostic(cli):
    result = cli.run("codex://not-found-" + "字" * 600, "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    parsed = result.stdout.splitlines()[2]
    assert parsed.startswith("Parsed URI: codex://not-found-字") and parsed.endswith("字…")
    assert len(parsed) == 512


@pytest.mark.parametrize(
    "scheme", ["opencode", "zcode", "codex", "kimi", "claude", "cursor", "pi", "deepchat", "cherry", "minimax"]
)
def test_missing_session_and_missing_provider_share_diagnostic(cli, scheme):
    expected = [
        "Diagnostic",
        "Summary: No matching session found.",
        f"Parsed URI: {scheme}://missing",
        f"  - scheme: {scheme}",
        "  - session_id: missing",
    ]
    for _ in range(2):
        result = cli.run(f"{scheme}://missing", "--head", "--lang", "en")
        assert result.returncode == 1, result.stdout + result.stderr
        assert not result.stderr
        assert result.stdout.splitlines()[:5] == expected
        shutil.rmtree(cli.root / "sources", ignore_errors=True)
    assert not (cli.root / "sources").exists()


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
def test_desktop_format_rejection_precedes_any_export(tmp_path, monkeypatch, provider):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    result = cli.run(f"{provider}://{identity}", "--format", "json,raw,print", "--output", "exports", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.splitlines()[:3] == [
        "Diagnostic",
        f"Summary: The current request uses an export capability {NAMES[provider]} does not support.",
        f"Capability gap: {NAMES[provider]} supports only json, markdown, print; requested raw",
    ]
    assert not (cli.root / "exports").exists()


@pytest.mark.parametrize("formats", ["json", "invalid", ""])
def test_head_format_conflict_precedes_lookup_and_format_validation(cli, formats):
    result = cli.run("codex://missing", "--head", "--format", formats, "--lang", "en")
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "❌ --head cannot be used with -format/--format.\n",
        "",
    )


def test_head_ignores_output_without_creating_directories(cli):
    result = cli.run(f"codex://{IDENTITY}", "--head", "--output", "exports", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"- URI: codex://{IDENTITY}" in result.stdout
    assert not (cli.root / "exports").exists()


@pytest.mark.parametrize("formats", ["", "json,", "xml", "raw,,json"])
def test_invalid_format_list_is_an_argument_error(cli, formats):
    result = cli.run("codex://missing", "--format", formats, "--lang", "en")
    assert result.returncode == 2
    assert not result.stdout
    assert result.stderr.startswith(f"error: Invalid format list: {formats}")


def test_lookup_failure_warns_then_prints_missing_session(cli):
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"broken synthetic database")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("opencode://missing", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == "⚠️  OpenCode session lookup failed: file is not a database\n"
    assert result.stdout.startswith("Diagnostic\nSummary: No matching session found.\n")
    assert cli.fixtures.source_manifest(cli.root) == before


def test_fallback_lookup_chooses_newest_matching_session(cli):
    cli.write([header(cwd="/older"), message("user", "Older")])
    cli.source.rename(cli.source.with_name("rollout-older.jsonl"))
    write_jsonl(cli.source.with_name("rollout-newer.jsonl"), [header(cwd="/newest", timestamp="2026-02-01T00:00:00Z")])
    result = cli.run(f"codex://{IDENTITY}", "--head", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"- CWD/Project: {Path('/newest')}" in result.stdout
