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
            "❌ --collect cannot be used with --list.",
        ),
        (
            ["--collect", "--dry-run", "--list", "--output", "prompt.txt"],
            1,
            "stdout",
            "❌ --collect cannot be used with --list.",
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
            "--json cannot be used with --collect --emit-prompt; supported modes are list, search, --stats, --providers, --head, --read, --message context, and --collect --verify-manifest.",
        ),
        (
            [URI, "--read", "--output", "prompt.txt"],
            1,
            "stderr",
            "--read cannot be used with --output.",
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
            "❌ --collect cannot be used with --list.",
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


def _option_flags(help_text: str, heading: str) -> list[str]:
    section = help_text.split(f"{heading}\n", 1)[1].split("\n\n", 1)[0]
    return [line.strip().split("  ", 1)[0] for line in section.splitlines() if line.strip()]


@pytest.mark.parametrize(
    ("subcommand", "expected_opt", "absent_opt"),
    [
        ("list", "--days", "--verify-manifest"),
        ("search", "--locate", "--verify-manifest"),
        ("browse", "--search", "--verify-manifest"),
        ("export", "--format", "--verify-manifest"),
        ("head", "--json", "--format"),
        ("read", "--cursor", "--verify-manifest"),
        ("read-prompt", "--lang", "--json"),
        ("collect", "--emit-prompt", "--cursor"),
        ("stats", "--days", "--time-field"),
        ("providers", "--json", "--days"),
        ("config", "--lang", "--days"),
        ("reindex", "--days", "--json"),
        ("shortcut", "--lang", "--days"),
    ],
)
def test_subcommand_help_is_focused_and_localized(
    cli: CliFixture,
    subcommand: str,
    expected_opt: str,
    absent_opt: str,
) -> None:
    en = cli.run(subcommand, "--help", "--lang", "en")
    assert en.returncode == 0 and not en.stderr
    assert f"agent-dump {subcommand}" in en.stdout
    assert "Usage:" in en.stdout and "Options:" in en.stdout and "Examples:" in en.stdout
    en_flags = _option_flags(en.stdout, "Options:")
    assert any(expected_opt in flag for flag in en_flags), en_flags
    assert all(absent_opt not in flag for flag in en_flags), en_flags

    zh = cli.run(subcommand, "--lang", "zh", "-h")
    assert zh.returncode == 0 and not zh.stderr
    assert f"agent-dump {subcommand}" in zh.stdout
    assert "用法:" in zh.stdout and "选项:" in zh.stdout and "示例:" in zh.stdout
    zh_flags = _option_flags(zh.stdout, "选项:")
    assert any(expected_opt in flag for flag in zh_flags), zh_flags
    assert all(absent_opt not in flag for flag in zh_flags), zh_flags


def test_global_help_is_preserved(cli: CliFixture) -> None:
    result = cli.run("--help", "--lang", "en")
    assert result.returncode == 0 and not result.stderr
    assert "Commands (equivalent to the listed options" in result.stdout
    assert "--verify-manifest" in result.stdout
    assert "--cursor" in result.stdout


@pytest.mark.parametrize(
    ("args", "lang", "stream", "expected"),
    [
        (["--read"], "en", "stderr", "--read requires a single session URI."),
        ([URI, "--read-prompt", "--json"], "en", "stderr", "--read-prompt cannot be used with --json."),
        (
            [URI, "--read", "--cursor", "r1.00", "--limit", "5", "--details"],
            "en",
            "stderr",
            "--cursor cannot be used with --limit, --details; it retains the original selection and budgets.",
        ),
        (["--locate"], "en", "stderr", "--locate requires --search."),
        (
            [URI, "--message", "abc:1", "--head"],
            "en",
            "stderr",
            "--message cannot be used with --head.",
        ),
        (
            [URI, "--message", "abc:1", "--json", "--format", "json"],
            "en",
            "stderr",
            "--message with --json cannot be used with --format.",
        ),
        (
            [URI, "--message", "abc:1", "--output", "out"],
            "en",
            "stderr",
            "--output with --message requires --format (json or markdown).",
        ),
        (
            ["--stats", "--time-field", "created"],
            "en",
            "stderr",
            "--time-field cannot be used with --stats; it requires list, search, browse, or interactive mode.",
        ),
        (
            ["--collect", "--verify-manifest", "manifest.txt", "--since", "2026-01-15"],
            "en",
            "stdout",
            "❌ --verify-manifest cannot be used with --since.",
        ),
        (
            [URI, "--read", "--output", "prompt.txt"],
            "zh",
            "stderr",
            "--read 不能与 --output 同时使用。",
        ),
    ],
)
def test_specific_conflict_diagnostics(
    cli: CliFixture,
    args: list[str],
    lang: str,
    stream: str,
    expected: str,
) -> None:
    result = cli.run(*args, "--lang", lang)
    assert result.returncode == 1, result.stdout + result.stderr
    assert getattr(result, stream).splitlines()[0] == expected
    assert not (result.stderr if stream == "stdout" else result.stdout)
