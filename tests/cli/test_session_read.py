"""Bounded, resumable reads and self-contained prompts over isolated Providers."""

import json
import os
import shlex
from typing import Any

from cli_fixture import IDENTITY, RUST, CliFixture, header, message

URI = f"codex://{IDENTITY}"


def read(cli: CliFixture, uri: str = URI, *args: str) -> dict[str, Any]:
    result = cli.run(uri, "--read", "--json", *args)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1
    assert document["kind"] == "read"
    assert document["has_more"] == (document["data"]["next_cursor"] is not None)
    return document


def test_read_prompt_needs_no_source_and_contains_executable_commands(cli: CliFixture) -> None:
    cli.source.write_text("invalid source: must not be read", encoding="utf-8")
    cli.environment["OPENCODE_DB"] = ":memory:"
    before = cli.fixtures.source_manifest(cli.root)
    uri = "codex://missing'$(touch injected)"
    result = cli.run(uri, "--read-prompt", "--lang", "en")
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    manifest = json.loads(result.stdout.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert manifest["read"]["argv"] == [str(RUST), uri, "--read", "--json"]
    assert manifest["continue"]["argv"] == [str(RUST), uri, "--read", "--cursor", "CURSOR", "--json"]
    assert "invalid source" not in result.stdout
    if os.name != "nt":
        for name in ("read", "continue", "filter", "details", "oldest_first", "head"):
            assert shlex.split(manifest[name]["command"]) == manifest[name]["argv"]
    else:
        assert manifest["read"]["command"].startswith("& '")
        assert "missing''$(touch injected)" in manifest["read"]["command"]
    assert cli.fixtures.source_manifest(cli.root) == before


def test_pagination_preserves_unicode_text_and_positions_without_gaps(cli: CliFixture) -> None:
    texts = ["first", "中文😺\n" * 9 + "结束", "third", "last"]
    cli.write([header(), *[message("user" if i % 2 == 0 else "assistant", body) for i, body in enumerate(texts)]])
    before = cli.fixtures.source_manifest(cli.root)
    page = read(cli, f"codex://threads/{IDENTITY}", "--limit", "2", "--max-chars", "7")
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
    assert positions == sorted(positions, reverse=True)
    assert fragments == dict(enumerate(texts, 1))
    assert cli.fixtures.source_manifest(cli.root) == before


def test_cursor_rejects_modified_source_other_session_and_invalid_offsets(cli: CliFixture) -> None:
    records = [header(), message("user", "Start"), message("assistant", "Answer")]
    cli.write(records)
    cursor = read(cli, URI, "--limit", "1")["data"]["next_cursor"]
    payload = json.loads(bytes.fromhex(cursor[3:]))
    invalid = ["invalid", "r1.ff"]
    for name, value in (("position", 0), ("position", 3), ("offset", 9999)):
        changed = {**payload, name: value}
        invalid.append("r1." + json.dumps(changed).encode().hex())
    for token in invalid:
        result = cli.run(URI, "--read", "--cursor", token, "--json")
        assert result.returncode == 1 and result.stdout == "" and result.stderr
    other = cli.run(URI.replace("000000000000", "000000000001"), "--read", "--cursor", cursor, "--json")
    assert other.returncode == 1 and other.stdout == ""
    cli.write([*records, message("user", "Appended")])
    stale = cli.run(URI, "--read", "--cursor", cursor, "--json")
    assert stale.returncode == 1 and stale.stdout == "" and stale.stderr


def test_read_spans_use_sanitized_unicode_offsets(cli: CliFixture) -> None:
    record = message("assistant", "unused")
    record["payload"]["content"] = [
        {"type": "output_text", "text": "中\u202e文\x00🙂"},
        {"type": "output_text", "text": "尾\t段"},
    ]
    cli.write([header(), record])
    first = read(cli, URI, "--max-chars", "4")["data"]
    fragment = first["messages"][0]
    assert fragment["text"] == "中文🙂\n"
    assert fragment["total_chars"] == 8
    assert [(span["start"], span["end"]) for span in fragment["text_spans"]] == [(0, 3)]
    second = read(cli, URI, "--cursor", first["next_cursor"])["data"]
    fragment = second["messages"][0]
    assert fragment["text"] == "\n尾\t段"
    assert (fragment["start"], fragment["end"]) == (4, 8)
    assert [(span["start"], span["end"]) for span in fragment["text_spans"]] == [(5, 8)]
    assert second["next_cursor"] is None


def test_read_since_until_filters_dated_segments_and_resumes_via_cursor(cli: CliFixture) -> None:
    undated = message("user", "no timestamp")
    undated.pop("timestamp")
    cli.write(
        [
            header(),
            message("user", "day one", stamp="2026-01-14T12:00:00+00:00"),
            message("assistant", "folded day one", stamp="2026-01-14T12:05:00+00:00"),
            message("assistant", "folded day two", stamp="2026-01-15T12:00:00+00:00"),
            undated,
            message("user", "day three", stamp="2026-01-16T12:00:00+00:00"),
            message("assistant", "day four", stamp="2026-01-17T12:00:00+00:00"),
        ]
    )
    unfiltered = read(cli, URI, "--limit", "1")["data"]
    assert "since" not in unfiltered["options"]
    assert "until" not in unfiltered["options"]

    first = read(cli, URI, "--since", "2026-01-15", "--until", "2026-01-16", "--order", "asc", "--limit", "1")
    data = first["data"]
    assert data["options"]["since"] == "2026-01-15"
    assert data["options"]["until"] == "2026-01-16"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["position"] == 2
    assert data["messages"][0]["text"] == "folded day two"
    assert [span["date"] for span in data["messages"][0]["text_spans"]] == ["2026-01-15"]
    assert first["has_more"] is True

    second = read(cli, URI, "--cursor", data["next_cursor"])
    data2 = second["data"]
    assert len(data2["messages"]) == 1
    assert data2["messages"][0]["position"] == 4
    assert data2["messages"][0]["text"] == "day three"
    assert [span["date"] for span in data2["messages"][0]["text_spans"]] == ["2026-01-16"]
    assert second["has_more"] is False
    assert data2["next_cursor"] is None


def test_read_date_filter_rejects_details_cursor_and_invalid_ranges(cli: CliFixture) -> None:
    cli.write([header(), message("user", "hello", stamp="2026-01-15T12:00:00+00:00")])
    cursor = read(cli, URI, "--limit", "1")["data"]["next_cursor"]

    details_conflict = cli.run(URI, "--read", "--details", "--since", "2026-01-15", "--json", "--lang", "en")
    assert details_conflict.returncode == 1
    assert details_conflict.stdout == ""
    assert "--details" in details_conflict.stderr and "--since" in details_conflict.stderr

    prompt_conflict = cli.run(URI, "--read-prompt", "--since", "2026-01-15", "--lang", "en")
    assert prompt_conflict.returncode == 1
    assert "--since" in prompt_conflict.stderr

    reversed_range = cli.run(URI, "--read", "--since", "2026-01-20", "--until", "2026-01-15", "--json", "--lang", "en")
    assert reversed_range.returncode == 1
    assert reversed_range.stdout == ""
    assert reversed_range.stderr

    for flag in ["--since=not-a-date", "--since=", "--until="]:
        invalid_date = cli.run(URI, "--read", flag, "--json", "--lang", "en")
        assert invalid_date.returncode == 1
        assert invalid_date.stdout == ""
        assert "Invalid date format" in invalid_date.stderr

    if cursor is None:
        cli.write(
            [
                header(),
                message("user", "one", stamp="2026-01-15T12:00:00+00:00"),
                message("assistant", "two", stamp="2026-01-15T12:01:00+00:00"),
            ]
        )
        cursor = read(cli, URI, "--limit", "1")["data"]["next_cursor"]
    assert cursor is not None
    cursor_conflict = cli.run(URI, "--read", "--cursor", cursor, "--since", "2026-01-15", "--json", "--lang", "en")
    assert cursor_conflict.returncode == 1
    assert cursor_conflict.stdout == ""
    assert "--since" in cursor_conflict.stderr
