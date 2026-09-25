"""Configuration and shortcut CLI contracts, without touching the user's home."""

import json
import os
from pathlib import Path
import shutil

from cli_fixture import IDENTITY
import pytest
import tomli as tomllib


def config_path(cli):
    base = Path(cli.environment["APPDATA"]) if os.name == "nt" else Path(cli.environment["HOME"]) / ".config"
    path = base / "agent-dump" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "source",
    [
        "",
        '[ai]\nprovider="openai"\nbase_url="https://example.invalid/v1"\nmodel="example"\napi_key="secret-key-value"\n',
        '[collect]\nsummary_concurrency=33\nsummary_timeout_seconds="180"\n[logging]\nenabled="off"\npath="~/logs/example"\n',
        "[collect]\nsummary_concurrency=true\nsummary_timeout_seconds=-3\n[export]\noutput=42\n",
        '[shortcut.example]\nparams=["date"]\nargs=["--list", "-q", "provider:codex"]\n[shortcut.empty]\nargs=[]\n',
        'bad = "unterminated',
        '[ai]\nbase_url="C:\\new\\folder"\n',
        '[export]\noutput=" with \\u001b[0m controls "\n[ai]\napi_key="😺1234终"\n',
    ],
)
def test_view_parity_and_key_masking(cli, lang, source):
    path = config_path(cli)
    path.write_text(source)
    cli.parity("--config", "view", "--lang", lang)
    assert path.read_text() == source


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "answers",
    [
        "\n\n\n\n./exported\ny\n",
        "1\nhttps://example.invalid/v1\nexample\nsecret-key-value\n./exported\ny\n",
        "2\nhttp://localhost:19999\nexample\nshort\n\nyes\n",
        "0\n",
        "\n\n\n\n\nn\n",
        "1\nhttp://remote.invalid\nexample\nsecret-key-value\n\ny\n",
    ],
)
def test_non_tty_edit_preserves_unknown_fields_and_comments(cli, lang, answers):
    path = config_path(cli)
    source = '# keep this comment\n[plugin."with.dot"]\nsecret = "unchanged" # keep suffix\n\n[export]\noutput = "old" # export suffix\n'
    results = []
    documents = []
    for candidate in ["python", "rust"]:
        path.write_text(source)
        result = cli.run(candidate, "--config", "edit", "--lang", lang, stdin=answers)
        results.append((result.returncode, result.stdout, result.stderr))
        documents.append(tomllib.loads(path.read_text()))
        assert "# keep this comment" in path.read_text()
        assert "# keep suffix" in path.read_text()
        assert "# export suffix" in path.read_text()
        assert "secret-key-value" not in result.stdout + result.stderr
        if result.returncode == 0 and os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600
    assert results[0] == results[1], results
    assert documents[0] == documents[1]


@pytest.mark.parametrize("source", ['bad = "unterminated', '[export]\noutput="C:\\new\\folder"\n'])
def test_edit_invalid_config_or_eof_leaves_file_unchanged(cli, source):
    path = config_path(cli)
    path.write_text(source)
    cli.parity("--config", "edit", "--lang", "en", exit_code=1)
    assert path.read_text() == source


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "args",
    [
        ["--shortcut", "sessions"],
        ["--shortcut", "scoped", "codex"],
        ["--shortcut", "dated", "2026-1-15"],
        ["--shortcut", "absent"],
        ["--shortcut"],
        ["--shortcut", "scoped"],
        ["--shortcut", "scoped", "a", "b"],
        ["--shortcut", "dated", "invalid"],
        ["--shortcut", "bad-brace"],
        ["--shortcut", "unknown-variable"],
    ],
)
def test_shortcut_expansion_and_diagnostics(cli, lang, args):
    path = config_path(cli)
    path.write_text("""
[shortcut.sessions]
params = []
args = ["--list", "-days", "36500"]
[shortcut.scoped]
params = ["provider"]
args = ["--list", "-query", "provider:{provider}", "-days", "36500"]
[shortcut.dated]
params = ["date"]
args = ["--list", "-query", "{date} {year} {month} {year_month}", "-days", "36500"]
[shortcut.bad-brace]
params = []
args = ["{"]
[shortcut.unknown-variable]
params = []
args = ["{unknown}"]
""")
    expected = (
        0
        if len(args) > 1
        and args[1] in {"sessions", "scoped", "dated"}
        and args[-1] in {"sessions", "codex", "2026-1-15"}
        else 1
    )
    cli.parity(*args, "--lang", lang, exit_code=expected)


@pytest.mark.parametrize("formats", ["json", "md", "raw", "json,md,raw"])
def test_default_output_respects_per_format_config_policy(cli, formats):
    path = config_path(cli)
    path.write_text('[export]\noutput = "configured"\n')
    results = []
    files = []
    for candidate in ["python", "rust"]:
        for directory in ["configured", "sessions"]:
            shutil.rmtree(cli.root / directory, ignore_errors=True)
        result = cli.run(candidate, f"codex://{IDENTITY}", "--format", formats, "--lang", "en")
        results.append((result.returncode, result.stdout, result.stderr))
        files.append(
            {
                str(f.relative_to(cli.root)): json.loads(f.read_text()) if f.suffix == ".json" else f.read_bytes()
                for directory in ["configured", "sessions"]
                for f in (cli.root / directory).rglob("*")
                if f.is_file()
            }
        )
    assert results[0] == results[1], results
    assert files[0] == files[1]


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
def test_edit_preserves_content_across_line_endings(cli, newline):
    path = config_path(cli)
    source = '# comment\n[export]\noutput="old" # suffix\n'.replace("\n", newline).encode()
    results = []
    for candidate in ["python", "rust"]:
        path.write_bytes(source)
        result = cli.run(candidate, "--config", "edit", "--lang", "en", stdin="\n\n\n\nnew\ny\n")
        results.append((result.returncode, result.stdout, result.stderr, path.read_bytes()))
    assert results[0] == results[1]


def test_invalid_utf8_config_diagnostic(cli):
    config_path(cli).write_bytes(b"\xff")
    cli.parity("--config", "view", "--lang", "en", exit_code=1)


def test_shortcut_allows_an_empty_format_specifier(cli):
    config_path(cli).write_text(
        '[shortcut.scoped]\nparams=["provider"]\nargs=["--list", "-q", "provider:{provider:}", "-d", "36500"]\n'
    )
    cli.parity("--shortcut", "scoped", "codex", "--lang", "en")
