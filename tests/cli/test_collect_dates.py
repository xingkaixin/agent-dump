"""Collect attributes text to its recorded local day, including folded replies."""

import json
from pathlib import Path

from cli_fixture import IDENTITY, CliFixture, header, message
import pytest
from test_collect import configure, only_session, server


def collect_args(since: str, until: str) -> list[str]:
    return ["--collect", "--since", since, "--until", until, "--query", "provider:codex", "--lang", "en"]


def test_long_session_is_split_by_text_date(cli: CliFixture) -> None:
    only_session(cli)
    cli.environment["TZ"] = "Asia/Shanghai"
    cli.write(
        [
            header(timestamp="2025-01-01T00:00:00Z"),
            message("user", "outside before", stamp="2026-01-13T04:00:00Z"),
            message("assistant", "day fourteen", stamp="2026-01-14T15:59:00Z"),
            message("assistant", "day fifteen", stamp="2026-01-14T16:01:00Z"),
            message("assistant", "day sixteen", stamp="2026-01-15T16:01:00Z"),
            message("user", "outside after", stamp="2026-01-17T04:00:00Z"),
        ]
    )
    chunks: dict[str, str] = {}
    groups: list[dict] = []

    def respond(payload: dict, _: int) -> tuple[int, dict]:
        prompt = payload["messages"][-1]["content"]
        envelopes = [json.loads(line) for line in prompt.splitlines() if line.startswith('{"untrusted_data"')]
        if "response_format" in payload:
            metadata, events = [item["content"] for item in envelopes]
            date = metadata.split("activity_date: ", 1)[1].splitlines()[0]
            chunks[date] = events
            text = json.dumps({"requests": [date]})
        else:
            assert "session_count: 1" in prompt
            groups.extend(json.loads(item["content"]) for item in envelopes)
            text = "# Report"
        return 200, {"choices": [{"message": {"content": text}}]}

    before = cli.fixtures.source_manifest(cli.root)
    args = collect_args("2026-01-14", "2026-01-16")
    with server(respond) as (url, _):
        configure(cli, url)
        result = cli.run(*args, "--save", "report.md")
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(chunks) == {"2026-01-14", "2026-01-15", "2026-01-16"}
    for date, word in zip(sorted(chunks), ["fourteen", "fifteen", "sixteen"], strict=True):
        assert chunks[date] == f"[agent_message] role=assistant text=day {word}"
    assert [group["date"] for group in groups] == sorted(chunks)
    assert all(group["session_uris"] == [f"codex://{IDENTITY}"] for group in groups)
    dry_run = cli.run(*args, "--dry-run")
    assert "Sessions: 1\nChunks: 3\n" in dry_run.stdout
    assert cli.fixtures.source_manifest(cli.root) == before


def test_no_work_in_range_is_empty_success(cli: CliFixture) -> None:
    only_session(cli)
    cli.write([header(), message("user", "outside period")])
    result = cli.run(*collect_args("2026-01-16", "2026-01-16"), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "No sessions" in result.stdout
    later = cli.run(*collect_args("2026-02-01", "2026-02-01"), "--dry-run")
    assert "No sessions" in later.stdout and "Scanning sessions: 0/0" in later.stderr
    handoff = cli.run(*collect_args("2026-01-16", "2026-01-16"), "--emit-prompt")
    assert handoff.returncode == 0 and not handoff.stdout
    cli.write([header(), message("user", "unknown date", stamp="invalid")])
    result = cli.run(*collect_args("2026-01-16", "2026-01-16"), "--dry-run")
    assert result.returncode == 0 and "No sessions" in result.stdout
    handoff = cli.run(*collect_args("2026-01-16", "2026-01-16"), "--emit-prompt")
    assert handoff.returncode == 0 and not handoff.stdout


def test_cursor_inferred_times_are_not_activity_dates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from desktop_fixture import NOW
    from test_cursor import cursor, put

    cli = cursor(tmp_path, monkeypatch)
    put(cli, "bubbleId:parent:c-undated", {"type": 2, "text": "undated answer"})
    put(cli, "composerData:parent", {"composerId": "parent", "createdAt": NOW, "subagentInfos": [{"id": "child"}]})
    put(
        cli,
        "bubble:child",
        {
            "chatMessages": [
                {"role": "assistant", "text": "child undated"},
                {"role": "assistant", "text": "child dated", "createdAt": NOW},
            ]
        },
    )
    read = cli.run("cursor://request-parent", "--read", "--json")
    assert read.returncode == 0, read.stderr
    fragments = json.loads(read.stdout)["data"]["messages"]
    dates = {item["text"]: [span["date"] for span in item["text_spans"]] for item in fragments}
    assert dates["undated answer"] == dates["child undated"] == [None]
    assert None not in dates["prompt"] + dates["child dated"]
