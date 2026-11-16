"""Mode precedence, conflicts, aliases and ignored options."""

from cli_fixture import IDENTITY, CliFixture
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
            ["--collect", "--dry-run", "--list", "--output", "prompt.txt"],
            1,
            "stdout",
            "❌ --collect cannot be used with URI/--interactive/--list.",
        ),
        (
            ["--collect", "--output", "prompt.txt"],
            1,
            "stdout",
            "❌ --output in --collect mode requires --emit-prompt (use --save for the collect report path).",
        ),
        (
            ["--collect", "--dry-run", "--output", "prompt.txt"],
            1,
            "stdout",
            "❌ --output in --collect mode requires --emit-prompt (use --save for the collect report path).",
        ),
        (
            ["--collect", "--emit-prompt", "--dry-run", "--output", "prompt.txt"],
            1,
            "stderr",
            "❌ --emit-prompt cannot be used with --dry-run.",
        ),
        (
            ["--collect", "--emit-prompt", "--output", "prompt.txt", "--json"],
            1,
            "stderr",
            "--json requires list, search, statistics, --providers, --head, --read, --message context, or --collect --verify-manifest mode.",
        ),
        (
            [URI, "--read", "--output", "prompt.txt"],
            1,
            "stderr",
            "--read and --read-prompt require a single session URI and cannot combine with other modes, --head, --message, --locate, --summary, export or collect options. --read-prompt does not accept --json.",
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


@pytest.mark.parametrize(
    ("args", "stream", "prefix"),
    [
        (["--verify-manifest", "manifest.txt"], "stdout", "❌ --verify-manifest requires --collect mode."),
        (
            ["--verify-manifest", "manifest.txt", "--json"],
            "stderr",
            "--json requires list, search, statistics, --providers, --head, --read, --message context, or --collect --verify-manifest mode.",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--emit-prompt"],
            "stderr",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--dry-run"],
            "stdout",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--dry-run", "--json"],
            "stderr",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--since", "2026-01-15"],
            "stdout",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--days", "7"],
            "stdout",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--output", "prompt.txt"],
            "stdout",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "-q", "provider:codex"],
            "stdout",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "agents://."],
            "stdout",
            "❌ --verify-manifest cannot be used with",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--list"],
            "stdout",
            "❌ --collect cannot be used with URI/--interactive/--list.",
        ),
    ],
)
def test_verify_manifest_mode_conflicts(cli: CliFixture, args: list[str], stream: str, prefix: str) -> None:
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(*args, "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert getattr(result, stream).startswith(prefix)
    assert not (result.stderr if stream == "stdout" else result.stdout)
    assert cli.fixtures.source_manifest(cli.root) == before
