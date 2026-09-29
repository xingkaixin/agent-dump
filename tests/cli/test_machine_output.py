"""Machine-readable output contracts using isolated provider records."""

import json

from cli_fixture import IDENTITY, header, message
import pytest


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_machine_list_search_stats(cli, lang):
    cli.write([header(), message("user", "unique-machine-needle"), message("assistant", "resolved")])
    common = ("--json", "-d", "36500", "-q", "provider:codex", "--lang", lang)
    before = cli.fixtures.source_manifest(cli.root)
    listed = cli.run("rust", "--list", *common)
    assert listed.returncode == 0, listed.stderr
    document = json.loads(listed.stdout)
    assert document["schema_version"] == 1
    assert document["kind"] == "list"
    assert document["status"] == "ok"
    record = next(item for item in document["data"] if item["id"] == IDENTITY)
    assert record["uri"] == f"codex://{IDENTITY}"
    assert record["working_directory"] == "/project"
    assert record["message_count"] == 2
    assert record["message_count_completeness"] == "exact"
    search = cli.run("rust", "--search", "unique-machine-needle", *common)
    assert search.returncode == 0, search.stderr
    found = json.loads(search.stdout)
    assert found["kind"] == "search"
    assert [item["id"] for item in found["data"]] == [IDENTITY]
    assert "unique-machine-needle" in found["data"][0]["snippet"]
    stats = cli.run("rust", "--stats", *common)
    assert stats.returncode == 0, stats.stderr
    counts = json.loads(stats.stdout)["data"]
    assert counts["total"]["sessions"] == len(document["data"])
    assert counts["total"]["known_messages"] >= 2
    assert cli.fixtures.source_manifest(cli.root) == before


def test_machine_empty_results_and_diagnostics(cli):
    result = cli.run("rust", "--search", "no-such-machine-match", "--json", "--format", "json", "-d", "36500")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"] == []
    assert result.stderr
    invalid = cli.run("rust", "--interactive", "--json")
    assert invalid.returncode == 1
    assert invalid.stdout == ""
    assert invalid.stderr


def test_machine_partial_discovery(cli):
    database = cli.root / "broken.sqlite"
    database.write_text("not sqlite")
    cli.environment["OPENCODE_DB"] = str(database)
    result = cli.run("rust", "--list", "--json", "-d", "36500")
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "partial"
    assert "opencode" in document["failed_providers"]
