"""Non-TTY selection remains usable in pipelines without a terminal UI."""

import re

import pytest


def test_provider_selection_exports_all_sessions(cli):
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("--interactive", "-d", "36500", "--lang", "en", "--output", "exports", stdin="1\nall\n")
    assert result.returncode == 0, result.stdout + result.stderr
    exported = re.search(r"✅ Successfully exported (\d+) sessions to exports/opencode/\n\Z", result.stdout)
    assert exported, result.stdout
    assert len(list((cli.root / "exports/opencode").glob("*.json"))) == int(exported[1]) > 0
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize(
    ("selection", "warning"),
    [
        ("0\n", "> ⚠️  Invalid selection: 0\n"),
        ("99\n", "> ⚠️  Invalid selection: 99\n"),
        ("q\n", "> ⚠️  Invalid input. Please enter a number.\n"),
        ("", "> \n⚠️  No input provided. Exiting.\n"),
    ],
)
def test_invalid_provider_selection_exits_without_export(cli, selection, warning):
    result = cli.run("--interactive", "-d", "36500", "--lang", "en", "--output", "exports", stdin=selection)
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.endswith(f"{warning}\n⚠️  No Agent Tool selected, exiting.\n")
    assert not (cli.root / "exports").exists()
