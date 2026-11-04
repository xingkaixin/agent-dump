"""Search locators and context ranges over isolated transcripts."""

import json

from cli_fixture import IDENTITY, header, message


def locate(cli, keyword, *args):
    result = cli.run("--search", keyword, "--locate", "--json", "-d", "36500", "-q", "provider:codex", *args)
    assert result.returncode == 0, result.stderr
    return next(item for item in json.loads(result.stdout)["data"] if item["id"] == IDENTITY)


def test_search_then_read_context_and_reject_stale_locator(cli):
    records = [header(), message("user", "alpha-marker"), message("assistant", "beta-marker"), message("user", "done")]
    cli.write(records)
    before = cli.fixtures.source_manifest(cli.root)
    found = locate(cli, "alpha-marker beta-marker")
    assert [item["position"] for item in found["locations"]] == [1, 2]
    locator = found["locations"][1]["locator"]
    args = (f"codex://{IDENTITY}", "--message", locator, "--json")
    result = cli.run(*args, "--before", "1", "--after", "0")
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["kind"] == "context"
    assert document["data"]["start"] == 1
    assert document["data"]["end"] == 2
    assert [item["position"] for item in document["data"]["messages"]] == [1, 2]
    assert document["data"]["messages"][1]["message"]["parts"][0]["text"] == "beta-marker"
    bounded = cli.run(*args, "--before", "4294967295", "--after", "4294967295")
    assert bounded.returncode == 0, bounded.stderr
    assert len(json.loads(bounded.stdout)["data"]["messages"]) == 3
    assert cli.fixtures.source_manifest(cli.root) == before
    cli.write([*records, message("assistant", "appended")])
    stale = cli.run(*args)
    assert stale.returncode == 1
    assert stale.stdout == ""
    assert stale.stderr
