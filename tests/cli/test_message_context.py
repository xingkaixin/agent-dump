"""Search locators and context ranges over isolated transcripts."""

import json

from cli_fixture import IDENTITY, call, header, message, output
import pytest


def locate(cli, keyword, *args):
    result = cli.run("rust", "--search", keyword, "--locate", "--json", "-d", "36500", "-q", "provider:codex", *args)
    assert result.returncode == 0, result.stderr
    return next(item for item in json.loads(result.stdout)["data"] if item["id"] == IDENTITY)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_search_then_read_context_and_reject_stale_locator(cli, lang):
    records = [header(), message("user", "alpha-marker"), message("assistant", "beta-marker"), message("user", "done")]
    cli.write(records)
    before = cli.fixtures.source_manifest(cli.root)
    found = locate(cli, "alpha-marker beta-marker", "--lang", lang)
    assert [item["position"] for item in found["locations"]] == [1, 2]
    locator = found["locations"][1]["locator"]
    args = (f"codex://{IDENTITY}", "--message", locator, "--json", "--lang", lang)
    result = cli.run("rust", *args, "--before", "1", "--after", "0")
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["kind"] == "context"
    assert document["data"]["start"] == 1
    assert document["data"]["end"] == 2
    assert [item["position"] for item in document["data"]["messages"]] == [1, 2]
    assert document["data"]["messages"][1]["message"]["parts"][0]["text"] == "beta-marker"
    bounded = cli.run("rust", *args, "--before", "4294967295", "--after", "4294967295")
    assert bounded.returncode == 0, bounded.stderr
    assert len(json.loads(bounded.stdout)["data"]["messages"]) == 3
    assert cli.fixtures.source_manifest(cli.root) == before
    cli.write([*records, message("assistant", "appended")])
    stale = cli.run("rust", *args)
    assert stale.returncode == 1
    assert stale.stdout == ""
    assert stale.stderr


def test_tool_locations_and_text_context(cli):
    cli.write([header(), message("user", "start"), call(arguments={"cmd": "tool-marker"}), output("result-marker")])
    found = locate(cli, "tool-marker")
    assert found["locations"]
    locator = found["locations"][0]["locator"]
    result = cli.run("rust", f"codex://{IDENTITY}", "--message", locator, "--before", "0", "--after", "0")
    assert result.returncode == 0, result.stderr
    assert "tool-marker" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["--locate", "--list"],
        ["--message", "invalid", "--list"],
        [f"codex://{IDENTITY}", "--message", "invalid", "--format", "json"],
        [f"codex://{IDENTITY}", "--message", "invalid", "--json"],
        [f"codex://{IDENTITY}", "--before", "2"],
    ],
)
def test_invalid_context_arguments(cli, args):
    result = cli.run("rust", *args)
    assert result.returncode != 0
    if "--json" in args:
        assert result.stdout == ""
        assert result.stderr


def test_locations_respect_role_filter(cli):
    cli.write([header(), message("user", "shared-marker"), message("assistant", "shared-marker")])
    found = locate(cli, "shared-marker", "-q", "provider:codex role:assistant")
    assert [item["role"] for item in found["locations"]] == ["assistant"]
    assert [item["position"] for item in found["locations"]] == [2]
