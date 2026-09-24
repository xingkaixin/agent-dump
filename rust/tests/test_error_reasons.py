"""Full diagnostics, including underlying source errors, through both CLIs."""

from cli_fixture import IDENTITY
import pytest
from test_title_cache import sessions


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b'{"entries": [',
        b'{"entries": [1,]}',
        b'{"a" 1}',
        b'{"a": [true false]}',
        b'"unterminated',
        b'{"\\q":1}',
        b'{"\\uZZZZ":1}',
        b'{"x":"line\nbreak"}',
        b'{"x":"\xff"}',
        b'{"x":"\xe4\xb8"}',
        b'{"x":"\xe4\xb8',
        b"{}{}",
        b"\xef\xbb\xbf{}",
        '{"中文": [1,]}'.encode(),
    ],
)
def test_json_and_utf8_title_index_causes_match(cli, language, raw):
    index = sessions(cli, "claude")
    index.write_bytes(raw)
    cli.parity("--list", "-q", "provider:claude", "-d", "36500", "--lang", language)
    cli.parity(f"claude://{IDENTITY}", "--head", "--lang", language)


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_title_index_directory_error_includes_reference_path_and_errno(cli, language, provider):
    index = sessions(cli, provider)
    if index.exists():
        index.unlink()
    index.mkdir()
    cli.parity("--list", "-q", f"provider:{provider}", "-d", "36500", "--lang", language)
    cli.parity(f"{provider}://{IDENTITY}", "--head", "--lang", language)


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("identity", ["..", "/", "folder/.."])
def test_unsafe_export_identity_has_complete_capability_diagnostic(cli, language, identity):
    import sqlite3

    from sqlite_fixture import create_legacy

    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session SET id = ?", (identity,))
        connection.execute("UPDATE message SET session_id = ?", (identity,))
    cli.parity(
        f"opencode://{identity}", "--format", "json,md,raw", "--output", "exports", "--lang", language, exit_code=1
    )
    assert not list((cli.root / "exports").rglob("*.*"))


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize(
    "raw", ["{broken", "[]", '"text"', '{"content": [5]}', '{"content": [{"type":"tool","name":5}]}']
)
def test_opencode_v2_bad_data_preserves_exact_reason(cli, monkeypatch, language, raw):
    import sqlite3

    from sqlite_fixture import create_v2

    path = create_v2(cli, monkeypatch)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session_message SET data = ? WHERE type = 'assistant'", (raw,))
    cli.parity(
        "opencode://ses_v2", "--format", "print,json,md,raw", "--output", "exports", "--lang", language, exit_code=1
    )


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("obstacle", ["destination", "provider-directory", "parent-directory"])
def test_export_filesystem_errors_keep_paths_and_partial_success(cli, language, obstacle):
    import re
    import shutil

    results = []
    for candidate in ("python", "rust"):
        output = cli.root / "exports"
        if output.is_file():
            output.unlink()
        else:
            shutil.rmtree(output, ignore_errors=True)
        if obstacle == "destination":
            (output / "codex" / f"{IDENTITY}.json").mkdir(parents=True)
        elif obstacle == "provider-directory":
            output.mkdir()
            (output / "codex").write_text("obstacle")
        else:
            output.write_text("obstacle")
        before = cli.fixtures.source_manifest(cli.root)
        result = cli.run(
            candidate, f"codex://{IDENTITY}", "--format", "json,md,raw", "--output", "exports", "--lang", language
        )
        normalized = re.sub(
            r"(\." + re.escape(IDENTITY) + r"\.json\.)[a-zA-Z0-9_]{8}(\.tmp)", r"\1<TEMP>\2", result.stdout
        )
        results.append((result.returncode, normalized, result.stderr))
        assert cli.fixtures.source_manifest(cli.root) == before
        assert not list((output / "codex").glob(".*.tmp"))
    assert results[0] == results[1], results
