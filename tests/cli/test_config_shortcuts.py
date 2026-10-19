"""Configuration and shortcut CLI contracts, without touching the user's home."""

import os
from pathlib import Path

import pytest
import tomli as tomllib


def config_path(cli):
    base = Path(cli.environment["APPDATA"]) if os.name == "nt" else Path(cli.environment["HOME"]) / ".config"
    path = base / "agent-dump" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize(("key", "masked"), [("secret-key-value", "sec**********lue"), ("😺1234终", "******")])
def test_view_masks_api_key(cli, key, masked):
    path = config_path(cli)
    source = f'[ai]\nprovider="openai"\nbase_url="https://example.invalid/v1"\nmodel="example"\napi_key="{key}"\n'
    path.write_text(source, encoding="utf-8")
    result = cli.run("--config", "view", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"  api_key: {masked}\n" in result.stdout
    assert key not in result.stdout + result.stderr
    assert path.read_text(encoding="utf-8") == source


def test_non_tty_edit_preserves_unknown_fields_and_comments(cli):
    path = config_path(cli)
    path.write_text(
        '# keep this comment\n[plugin."with.dot"]\nsecret = "unchanged" # keep suffix\n\n'
        '[export]\noutput = "old" # export suffix\n'
    )
    answers = "1\nhttps://example.invalid/v1\nexample\nsecret-key-value\n./exported\ny\n"
    result = cli.run("--config", "edit", "--lang", "en", stdin=answers)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "secret-key-value" not in result.stdout + result.stderr
    content = path.read_text()
    for comment in ("# keep this comment", "# keep suffix", "# export suffix"):
        assert comment in content
    assert tomllib.loads(content) == {
        "plugin": {"with.dot": {"secret": "unchanged"}},
        "export": {"output": "./exported"},
        "ai": {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "example",
            "api_key": "secret-key-value",
        },
    }
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("source", "answers"),
    [
        ('[export]\noutput = "old"\n', "0\n"),
        ('[export]\noutput = "old"\n', "\n\n\n\n\nn\n"),
        ('bad = "unterminated', ""),
        ('[export]\noutput="C:\\new\\folder"\n', ""),
    ],
)
def test_cancelled_or_failed_edit_leaves_file_unchanged(cli, source, answers):
    path = config_path(cli)
    path.write_text(source)
    result = cli.run("--config", "edit", "--lang", "en", stdin=answers)
    assert result.returncode == 1, result.stdout + result.stderr
    assert path.read_text() == source


def test_invalid_utf8_config_diagnostic(cli):
    path = config_path(cli)
    path.write_bytes(b"\xff")
    result = cli.run("--config", "view", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff" in result.stdout
    assert path.read_bytes() == b"\xff"


@pytest.mark.parametrize(
    ("args", "code", "first_line"),
    [
        (["sessions"], 0, "🚀 Agent Session Exporter"),
        (["scoped", "codex"], 0, "🚀 Agent Session Exporter"),
        (["dated", "2026-1-15"], 0, "🚀 Agent Session Exporter"),
        (["absent"], 1, "❌ Shortcut not found: absent"),
        (["scoped"], 1, "❌ Shortcut scoped expects 1 args, got 0."),
        (["scoped", "a", "b"], 1, "❌ Shortcut scoped expects 1 args, got 2."),
        (["dated", "invalid"], 1, "❌ Invalid shortcut date value. Use YYYY-MM-DD or YYYYMMDD."),
        (["bad-brace"], 1, "❌ Invalid shortcut template. format/conversion syntax is not supported."),
        (["unknown-variable"], 1, "❌ Shortcut template references unknown variable: unknown"),
    ],
)
def test_shortcut_expansion_and_diagnostics(cli, args, code, first_line):
    config_path(cli).write_text("""
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
    result = cli.run("--shortcut", *args, "--lang", "en")
    assert result.returncode == code, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.splitlines()[0] == first_line
    if args == ["scoped", "codex"]:
        assert "matching 'providers=codex'" in result.stdout
        assert "📁 OpenCode" not in result.stdout
    if args == ["dated", "2026-1-15"]:
        assert "matching '20260115 2026 01 2026-01'" in result.stdout
