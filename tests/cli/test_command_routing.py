"""Mode precedence, conflicts, aliases and ignored options."""

from cli_fixture import IDENTITY
import pytest


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "args",
    [
        ["--collect", "--dry-run", "--list"],
        ["--collect", "--dry-run", "--interactive"],
        ["--collect", "--dry-run", f"codex://{IDENTITY}"],
        ["--emit-prompt"],
        ["--list", "--emit-prompt"],
        ["--providers", "--collect", "--emit-prompt"],
        ["--collect", "--dry-run", "--emit-prompt"],
        [f"codex://{IDENTITY}", "--head", "--summary"],
        [f"codex://{IDENTITY}", "--head", "--format", "json", "--summary"],
        ["--providers", "--stats", "--list", "--summary", "--head", "-q", "invalid:empty"],
        ["--capabilities"],
        ["--list", "--head", "--summary", "-d", "36500"],
        ["--stats", "--reindex", "--list", "-d", "36500"],
        [f"codex://{IDENTITY}", "--head", "--list", "-q", "provider:missing"],
        ["--list", "--format", "json", "--output", "ignored", "-d", "36500"],
        ["--search", "benchmark", "--format", "print", "--output", "ignored", "-d", "36500"],
        ["-days", "36500"],
    ],
)
def test_mode_contract(cli, lang, args):
    result = cli.run("python", *args, "--lang", lang)
    cli.parity(*args, "--lang", lang, exit_code=result.returncode)
