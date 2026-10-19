"""Mode precedence, conflicts, aliases and ignored options."""

from cli_fixture import IDENTITY
import pytest

URI = f"codex://{IDENTITY}"


@pytest.mark.parametrize(
    ("args", "code", "stream", "first_line"),
    [
        (
            ["--collect", "--dry-run", "--list"],
            1,
            "stdout",
            "❌ --collect cannot be used with URI/--interactive/--list.",
        ),
        (
            ["--collect", "--dry-run", "--interactive"],
            1,
            "stdout",
            "❌ --collect cannot be used with URI/--interactive/--list.",
        ),
        (["--collect", "--dry-run", URI], 1, "stdout", "❌ --collect cannot be used with URI/--interactive/--list."),
        (["--emit-prompt"], 1, "stderr", "❌ --emit-prompt requires --collect mode."),
        (["--list", "--emit-prompt"], 1, "stderr", "❌ --emit-prompt requires --collect mode."),
        (["--providers", "--collect", "--emit-prompt"], 1, "stderr", "❌ --emit-prompt requires --collect mode."),
        (["--collect", "--dry-run", "--emit-prompt"], 1, "stderr", "❌ --emit-prompt cannot be used with --dry-run."),
        ([URI, "--head", "--summary"], 1, "stdout", "❌ --head cannot be used with --summary."),
        (
            [URI, "--head", "--format", "json", "--summary"],
            1,
            "stdout",
            "❌ --head cannot be used with -format/--format.",
        ),
        (
            ["--providers", "--stats", "--list", "--summary", "--head", "-q", "invalid:empty"],
            0,
            "stdout",
            "⚠️  Ignored lower-priority mode options: --stats, --list",
        ),
        (["--capabilities"], 0, "stdout", "Provider capabilities"),
        (
            ["--stats", "--reindex", "--list", "-d", "36500"],
            0,
            "stdout",
            "⚠️  Ignored lower-priority mode options: --reindex, --list",
        ),
        (
            [URI, "--head", "--list", "-q", "provider:missing"],
            0,
            "stdout",
            "⚠️  Ignored lower-priority mode options: --list",
        ),
    ],
)
def test_mode_contract(cli, args, code, stream, first_line):
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(*args, "--lang", "en")
    assert result.returncode == code, result.stdout + result.stderr
    assert getattr(result, stream).splitlines()[0] == first_line
    if code:
        assert not (result.stderr if stream == "stdout" else result.stdout)
    assert cli.fixtures.source_manifest(cli.root) == before
