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
        (["--emit-prompt"], 1, "stderr", "❌ --emit-prompt requires --collect mode."),
        ([URI, "--head", "--summary"], 1, "stdout", "❌ --head cannot be used with --summary."),
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
