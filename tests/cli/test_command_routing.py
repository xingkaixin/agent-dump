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


@pytest.mark.parametrize(
    ("args", "ignored"),
    [
        (["--interactive", "agents://."], None),
        (["--stats", "--interactive", "agents://."], "--interactive, agents:// query URI"),
    ],
)
def test_query_uri_is_reported_ignored_only_when_unused(cli, args, ignored):
    result = cli.run(*args, "--lang", "en", stdin="\n")
    warning = "⚠️  Ignored lower-priority mode options: "
    reported = [line.removeprefix(warning) for line in result.stdout.splitlines() if line.startswith(warning)]
    assert reported == ([ignored] if ignored else []), result.stdout + result.stderr


def test_collect_only_options_are_reported_ignored(cli):
    result = cli.run("--list", "--since", "2026-01-01", "--dry-run", "--save", "report.md", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == "⚠️  --since, --dry-run, --save only apply to --collect and will be ignored."
    assert not (cli.root / "report.md").exists()


def test_interactive_rejects_an_invalid_format_as_usage_error(cli):
    result = cli.run("--interactive", "--format", "bogus", "--lang", "en", stdin="\n")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "invalid format list: bogus" in result.stderr
    assert not result.stdout


@pytest.mark.parametrize("mode", ["--list", "--stats"])
def test_unreadable_requested_provider_is_not_an_empty_result(cli, mode):
    database = cli.root / "broken.sqlite"
    database.write_text("not sqlite")
    cli.environment["OPENCODE_DB"] = str(database)
    result = cli.run(mode, "-q", "provider:opencode", "-d", "36500", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
