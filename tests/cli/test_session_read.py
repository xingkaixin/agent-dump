"""Bounded, resumable reads and self-contained prompts over isolated Providers."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

from cli_fixture import IDENTITY, RUST, CliFixture, call, header, make_cli, message, output, reasoning
from desktop_fixture import desktop
import pytest
from sqlite_fixture import create_legacy
from test_claude import create as create_claude, event
from test_cursor import cursor as create_cursor
from test_kimi import create as create_kimi
from test_pi import create as create_pi, message as pi_message

SCHEMES = ["codex", "claude", "opencode", "zcode", "kimi", "cursor", "pi", "deepchat", "cherry", "minimax"]
URI = f"codex://{IDENTITY}"


def read(cli: CliFixture, uri: str = URI, *args: str) -> dict[str, Any]:
    result = cli.run("rust", uri, "--read", "--json", *args)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1
    assert document["kind"] == "read"
    assert document["has_more"] == (document["data"]["next_cursor"] is not None)
    return document


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_read_prompt_needs_no_source_and_contains_executable_commands(cli: CliFixture, scheme: str, lang: str) -> None:
    cli.source.write_text("invalid source: must not be read", encoding="utf-8")
    cli.environment["OPENCODE_DB"] = ":memory:"
    before = cli.fixtures.source_manifest(cli.root)
    uri = f"{scheme}://missing'$(touch injected)"
    result = cli.run("rust", uri, "--read-prompt", "--lang", lang)
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    manifest = json.loads(result.stdout.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert manifest["read"]["argv"] == [str(RUST), uri, "--read", "--json"]
    assert manifest["continue"]["argv"] == [str(RUST), uri, "--read", "--cursor", "CURSOR", "--json"]
    assert "next_cursor" in result.stdout and "has_more" in result.stdout
    assert "invalid source" not in result.stdout
    if os.name != "nt":
        for name in ("read", "continue", "filter", "details", "oldest_first", "head"):
            assert shlex.split(manifest[name]["command"]) == manifest[name]["argv"]
    else:
        assert manifest["read"]["command"].startswith("& '")
        assert "missing''$(touch injected)" in manifest["read"]["command"]
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("scheme", SCHEMES)
def test_prompt_read_command_works_for_every_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    if scheme == "zcode" and not sys.platform.startswith(("darwin", "win")):
        pytest.skip("ZCode has source paths only on macOS and Windows")
    if scheme in {"deepchat", "cherry", "minimax"}:
        cli, identity = desktop(tmp_path, monkeypatch, scheme)
    elif scheme == "cursor":
        cli, identity = create_cursor(tmp_path, monkeypatch), "request-parent"
    else:
        cli, identity = make_cli(tmp_path, monkeypatch), IDENTITY
        if scheme == "claude":
            create_claude(cli, [event("user", "Prompt"), event("assistant", [{"type": "text", "text": "Answer"}])])
        elif scheme == "pi":
            create_pi(
                cli, [pi_message("user", "Prompt", identity="u"), pi_message("assistant", "Answer", identity="a")]
            )
        elif scheme == "kimi":
            create_kimi(
                cli, context=[{"role": "user", "content": "Prompt"}, {"role": "assistant", "content": "Answer"}]
            )
        elif scheme == "opencode":
            identity = "ses_bench_000000"
        elif scheme == "zcode":
            create_legacy(cli, "zcode")
            identity = "ses_old"
    before = cli.fixtures.source_manifest(cli.root)
    uri = f"{scheme}://{identity}"
    prompt = cli.run("rust", uri, "--read-prompt")
    assert prompt.returncode == 0, prompt.stderr
    manifest = json.loads(prompt.stdout.split("```json\n", 1)[1].split("\n```", 1)[0])
    result = subprocess.run(  # noqa: S603
        manifest["read"]["argv"],
        cwd=cli.root,
        env=cli.environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "ok"
    assert document["data"]["uri"] == uri
    assert document["data"]["messages"]
    assert sum(len(item["text"]) for item in document["data"]["messages"]) <= 12000
    assert not document["has_more"]
    page = read(cli, uri, "--limit", "1")
    paged = list(page["data"]["messages"])
    cursors = set()
    while page["has_more"]:
        cursor = page["data"]["next_cursor"]
        assert cursor not in cursors
        cursors.add(cursor)
        page = read(cli, uri, "--cursor", cursor)
        paged.extend(page["data"]["messages"])
    assert paged == document["data"]["messages"]
    assert cli.fixtures.source_manifest(cli.root) == before
    assert not (cli.root / "sessions").exists()


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_pagination_preserves_unicode_text_and_positions_without_gaps(cli: CliFixture, order: str) -> None:
    texts = ["first", "中文😺\n" * 9 + "结束", "third", "last"]
    cli.write([header(), *[message("user" if i % 2 == 0 else "assistant", body) for i, body in enumerate(texts)]])
    before = cli.fixtures.source_manifest(cli.root)
    page = read(cli, f"codex://threads/{IDENTITY}", "--limit", "2", "--max-chars", "7", "--order", order)
    fragments: dict[int, str] = {}
    positions = []
    cursors = set()
    while True:
        assert page["status"] == "ok"
        data = page["data"]
        assert data["total_messages"] == 4
        assert len(data["messages"]) <= 2
        assert sum(len(item["text"]) for item in data["messages"]) <= 7
        for item in data["messages"]:
            position = item["position"]
            positions.append(position)
            previous = fragments.get(position, "")
            assert item["start"] == len(previous)
            assert item["end"] == item["start"] + len(item["text"])
            assert item["total_chars"] == len(texts[position - 1])
            assert item["truncated"] == (item["start"] != 0 or item["end"] != item["total_chars"])
            assert item["locator"] == f"{data['revision']}:{position}"
            fragments[position] = previous + item["text"]
        cursor = data["next_cursor"]
        if cursor is None:
            break
        assert cursor not in cursors
        cursors.add(cursor)
        page = read(cli, URI, "--cursor", cursor)
    assert positions == sorted(positions, reverse=order == "desc")
    assert fragments == dict(enumerate(texts, 1))
    assert cli.fixtures.source_manifest(cli.root) == before


def test_filter_before_pagination_and_details_are_opt_in(cli: CliFixture) -> None:
    cli.write(
        [
            header(),
            message("user", "DATABASE\n   locked first"),
            message("assistant", "database locked answer"),
            message("user", "database locked last"),
            reasoning("reason-only"),
            call(arguments={"cmd": "tool-only"}),
            output("tool-result"),
        ]
    )
    page = read(cli, URI, "--role", "USER", "--match", "database locked", "--limit", "1")
    assert [item["position"] for item in page["data"]["messages"]] == [3]
    cursor = page["data"]["next_cursor"]
    page = read(cli, URI, "--cursor", cursor)
    assert [item["position"] for item in page["data"]["messages"]] == [1]
    assert not page["has_more"]
    for keyword in ("tool-only", "reason-only"):
        assert read(cli, URI, "--match", keyword)["data"]["messages"] == []
        found = read(cli, URI, "--match", keyword, "--details")
        assert keyword in found["data"]["messages"][0]["text"]
    locator = page["data"]["messages"][0]["locator"]
    context = cli.run("rust", URI, "--message", locator, "--before", "0", "--after", "0", "--json")
    assert context.returncode == 0, context.stderr
    assert json.loads(context.stdout)["data"]["messages"][0]["position"] == 1
    cli.write([header(), message("user", "-days")])
    assert read(cli, URI, "--match=-days")["data"]["messages"][0]["text"] == "-days"


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_empty_partial_and_text_output(cli: CliFixture, lang: str) -> None:
    cli.write([header()])
    page = read(cli, URI, "--lang", lang)
    assert page["data"]["messages"] == []
    assert not page["has_more"]
    cli.write([header(), message("user", "Visible")], suffix=b"{bad-json}\n")
    partial = cli.run("rust", URI, "--read", "--json", "--lang", lang)
    assert partial.returncode == 0
    assert partial.stderr
    assert json.loads(partial.stdout)["status"] == "partial"
    text = cli.run("rust", URI, "--read", "--lang", lang)
    assert text.returncode == 0 and "Visible" in text.stdout
    assert "已读完" in text.stdout if lang == "zh" else "End of matching" in text.stdout


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_cursor_rejects_modified_source_other_session_and_invalid_offsets(cli: CliFixture, lang: str) -> None:
    records = [header(), message("user", "Start"), message("assistant", "Answer")]
    cli.write(records)
    cursor = read(cli, URI, "--limit", "1")["data"]["next_cursor"]
    payload = json.loads(bytes.fromhex(cursor[3:]))
    invalid = ["invalid", "r1.ff"]
    for name, value in (("position", 0), ("position", 3), ("offset", 9999)):
        changed = {**payload, name: value}
        invalid.append("r1." + json.dumps(changed).encode().hex())
    for token in invalid:
        result = cli.run("rust", URI, "--read", "--cursor", token, "--json", "--lang", lang)
        assert result.returncode == 1 and result.stdout == "" and result.stderr
    other = cli.run("rust", URI.replace("000000000000", "000000000001"), "--read", "--cursor", cursor, "--json")
    assert other.returncode == 1 and other.stdout == ""
    cli.write([*records, message("user", "Appended")])
    stale = cli.run("rust", URI, "--read", "--cursor", cursor, "--json", "--lang", lang)
    assert stale.returncode == 1 and stale.stdout == "" and stale.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--read"],
        ["--read-prompt"],
        ["agents://.", "--read"],
        ["unknown://id", "--read-prompt"],
        [URI, "--read", "--read-prompt"],
        [URI, "--read-prompt", "--json"],
        [URI, "--read", "--search", "needle"],
        [URI, "--read", "--query", "role:user"],
        [URI, "--read", "--format", "json"],
        [URI, "--read", "--head"],
        [URI, "--read", "--message", "locator"],
        [URI, "--read", "--collect"],
        [URI, "--limit", "2"],
        [URI, "--read", "--limit", "0"],
        [URI, "--read", "--limit", "101"],
        [URI, "--read", "--max-chars", "0"],
        [URI, "--read", "--max-chars", "100001"],
        [URI, "--read", "--match", "  "],
        [URI, "--read", "--role", "  "],
        [URI, "--read", "--cursor", "value", "--details"],
        [URI, "--read", "--cursor", "value", "--limit", "1"],
    ],
)
def test_invalid_read_arguments_fail_without_stdout(cli: CliFixture, args: list[str]) -> None:
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", *args)
    assert result.returncode != 0 and result.stdout == "" and result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before
