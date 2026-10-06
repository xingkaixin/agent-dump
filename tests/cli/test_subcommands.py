"""Subcommands are aliases for the existing option-based modes."""

import json

from cli_fixture import IDENTITY, CliFixture
import pytest


@pytest.mark.parametrize(
    ("command", "options"),
    [
        (["list", "-d", "36500", "--json"], ["--list", "-d", "36500", "--json"]),
        (["search", "Hello", "-d", "36500", "--json"], ["--search", "Hello", "-d", "36500", "--json"]),
        (["head", f"codex://{IDENTITY}", "--json"], [f"codex://{IDENTITY}", "--head", "--json"]),
        (["read", f"codex://{IDENTITY}", "--json"], [f"codex://{IDENTITY}", "--read", "--json"]),
        (["providers", "--json"], ["--providers", "--json"]),
        (["stats", "-d", "36500", "--json"], ["--stats", "-d", "36500", "--json"]),
    ],
)
def test_subcommand_matches_option_mode(cli: CliFixture, command: list[str], options: list[str]) -> None:
    subcommand = cli.run("rust", *command, "--lang", "en")
    option = cli.run("rust", *options, "--lang", "en")
    assert subcommand.returncode == option.returncode == 0, subcommand.stderr
    assert (subcommand.stdout, subcommand.stderr) == (option.stdout, option.stderr)


def test_export_subcommand_defaults_uri_exports_to_json(cli: CliFixture) -> None:
    result = cli.run("rust", "export", f"codex://{IDENTITY}", "--output", "exports", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    exported = cli.root / "exports" / "codex" / f"{IDENTITY}.json"
    assert json.loads(exported.read_text())["id"] == IDENTITY

    result = cli.run("rust", "export", f"codex://{IDENTITY}", "--format", "md", "--output", "md", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (cli.root / "md" / "codex" / f"{IDENTITY}.json").exists()


def test_subcommand_help_and_unknown_words(cli: CliFixture) -> None:
    help_result = cli.run("rust", "search", "--help", "--lang", "en")
    assert help_result.returncode == 0
    assert "search <TERMS>" in help_result.stdout

    unknown = cli.run("rust", "lists", "--lang", "en")
    assert unknown.returncode == 1
