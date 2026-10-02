"""Search locators and context ranges over isolated transcripts."""

import json

from cli_fixture import IDENTITY, CliFixture, call, header, message, output
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


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_export_context_preserves_source_and_absolute_positions(cli: CliFixture, lang: str) -> None:
    cli.write(
        [
            header(),
            message("user", "before-marker"),
            message("assistant", "target-marker 中文"),
            message("user", "after-marker"),
            message("assistant", "outside-marker"),
        ]
    )
    locator = locate(cli, "target-marker")["locations"][0]["locator"]
    uri = f"codex://{IDENTITY}"
    before = cli.fixtures.source_manifest(cli.root)
    full = cli.run("rust", uri, "--format", "json,md", "--output", "exports")
    assert full.returncode == 0, full.stderr
    directory = cli.root / "exports" / "codex"
    original = {path: path.read_bytes() for path in directory.iterdir()}
    args = ("--message", locator, "--before", "1", "--after", "1", "--lang", lang)
    result = cli.run("rust", f"codex://threads/{IDENTITY}", *args, "--format", "json,md", "--output", "exports")
    assert result.returncode == 0 and not result.stderr
    document = json.loads((directory / f"{IDENTITY}.messages-1-3.json").read_text())
    printed = cli.run("rust", uri, *args, "--json")
    assert document == json.loads(printed.stdout)
    assert document["data"]["locator"] == locator and document["data"]["uri"] == uri
    assert [item["position"] for item in document["data"]["messages"]] == [1, 2, 3]
    markdown = (directory / f"{IDENTITY}.messages-1-3.md").read_text()
    for text in (uri, locator, "Messages: 1–3 of 4", "Status: ok", "## 2. assistant", "target-marker 中文"):
        assert text in markdown
    assert "outside-marker" not in markdown and "outside-marker" not in json.dumps(document)
    clipped = cli.run(
        "rust",
        uri,
        "--message",
        locator,
        "--before",
        "0",
        "--after",
        "4294967295",
        "--format",
        "json",
        "--output",
        "exports",
    )
    assert clipped.returncode == 0, clipped.stderr
    clipped_data = json.loads((directory / f"{IDENTITY}.messages-2-4.json").read_text())["data"]
    assert [item["position"] for item in clipped_data["messages"]] == [2, 3, 4]
    assert all(path.read_bytes() == contents for path, contents in original.items())
    assert cli.fixtures.source_manifest(cli.root) == before


def test_export_context_rejects_source_paths_and_stale_locators(cli: CliFixture) -> None:
    records = [header(), message("user", "target-marker"), message("assistant", "done")]
    cli.write(records)
    locator = locate(cli, "target-marker")["locations"][0]["locator"]
    args = (f"codex://{IDENTITY}", "--message", locator, "--format", "json,md", "--output")
    before = cli.fixtures.source_manifest(cli.root)
    denied = cli.run("rust", *args, str(cli.source.parent / "exports"))
    assert denied.returncode == 1
    assert "outside the Provider source directory" in denied.stdout + denied.stderr
    assert not (cli.source.parent / "exports").exists()
    assert cli.fixtures.source_manifest(cli.root) == before
    cli.write([*records, message("user", "changed")])
    stale = cli.run("rust", *args, "exports")
    assert stale.returncode == 1
    assert "Message locator no longer matches" in stale.stdout + stale.stderr
    assert not (cli.root / "exports").exists()


def test_export_context_marks_recoverable_read_failures_partial(cli: CliFixture) -> None:
    cli.write([header(), message("user", "target-marker")], suffix=b"invalid-json\n")
    locator = locate(cli, "target-marker")["locations"][0]["locator"]
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--message", locator, "--format", "json,md", "--output", "exports")
    assert result.returncode == 0 and result.stderr
    directory = cli.root / "exports" / "codex"
    document = json.loads(next(directory.glob("*.json")).read_text())
    assert document["status"] == "partial"
    assert "Status: partial" in next(directory.glob("*.md")).read_text()
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize(
    "args",
    [
        ["--head", "--format", "json"],
        ["--summary", "--format", "json"],
        ["--json", "--format", "json"],
        ["--format", "raw"],
        ["--format", "print"],
        ["--output", "exports"],
    ],
)
def test_export_context_rejects_ambiguous_modes(cli: CliFixture, args: list[str]) -> None:
    cli.write([header(), message("user", "target-marker")])
    locator = locate(cli, "target-marker")["locations"][0]["locator"]
    result = cli.run("rust", f"codex://{IDENTITY}", "--message", locator, *args)
    assert result.returncode == 1 and result.stderr
    assert not result.stdout
    assert not (cli.root / "exports").exists()
    assert not (cli.root / "sessions").exists()
