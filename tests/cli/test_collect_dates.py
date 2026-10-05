"""Collect attributes text to its recorded local day, including folded replies."""

import json
from pathlib import Path

from cli_fixture import IDENTITY, CliFixture, header, message, write_jsonl
import pytest
from test_collect import configure, only_session, server


def collect_args(since: str, until: str) -> list[str]:
    return ["--collect", "--since", since, "--until", until, "--query", "provider:codex", "--lang", "en"]


@pytest.mark.parametrize("mode", ["pm", "insight"])
def test_long_session_is_split_by_text_date(cli: CliFixture, mode: str) -> None:
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
            field = "requests" if mode == "pm" else "scene"
            text = json.dumps({field: [date]})
        else:
            assert "session_count: 1" in prompt
            groups.extend(json.loads(item["content"]) for item in envelopes)
            text = "# Report"
        return 200, {"choices": [{"message": {"content": text}}]}

    before = cli.fixtures.source_manifest(cli.root)
    args = collect_args("2026-01-14", "2026-01-16")
    with server(respond) as (url, _):
        configure(cli, url)
        result = cli.run("rust", *args, "--collect-mode", mode, "--save", "report.md")
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(chunks) == {"2026-01-14", "2026-01-15", "2026-01-16"}
    for date, word in zip(sorted(chunks), ["fourteen", "fifteen", "sixteen"], strict=True):
        assert chunks[date] == f"[agent_message] role=assistant text=day {word}"
    assert [group["date"] for group in groups] == sorted(chunks)
    assert all(group["session_uris"] == [f"codex://{IDENTITY}"] for group in groups)
    dry_run = cli.run("rust", *args, "--dry-run")
    assert "Sessions: 1\nChunks: 3\n" in dry_run.stdout
    assert cli.fixtures.source_manifest(cli.root) == before


def test_report_omits_undated_text_and_marks_gap(cli: CliFixture) -> None:
    only_session(cli)
    cli.write([header(), message("user", "dated work"), message("assistant", "unknown work", stamp="invalid")])
    prompts: list[str] = []

    def respond(payload: dict, _: int) -> tuple[int, dict]:
        prompts.append(payload["messages"][-1]["content"])
        text = json.dumps({"requests": ["dated work"]}) if "response_format" in payload else "# Report"
        return 200, {"choices": [{"message": {"content": text}}]}

    with server(respond) as (url, _):
        configure(cli, url)
        result = cli.run("rust", *collect_args("2026-01-15", "2026-01-15"), "--save", "report.md")
    assert result.returncode == 0, result.stderr
    assert all("unknown work" not in prompt for prompt in prompts)
    report = (cli.root / "report.md").read_text()
    assert "Incomplete date coverage" in report and f"codex://{IDENTITY}" in report


def test_no_work_in_range_is_empty_success(cli: CliFixture) -> None:
    only_session(cli)
    cli.write([header(), message("user", "outside period")])
    result = cli.run("rust", *collect_args("2026-01-16", "2026-01-16"), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "No sessions" in result.stdout
    handoff = cli.run("rust", *collect_args("2026-01-16", "2026-01-16"), "--emit-prompt")
    assert handoff.returncode == 0 and not handoff.stdout
    cli.write([header(), message("user", "unknown date", stamp="invalid")])
    result = cli.run("rust", *collect_args("2026-01-16", "2026-01-16"), "--dry-run")
    assert result.returncode == 1 and "Incomplete date coverage" in result.stderr
    handoff = cli.run("rust", *collect_args("2026-01-16", "2026-01-16"), "--emit-prompt")
    assert handoff.returncode == 1 and not handoff.stdout


def test_handoff_read_spans_preserve_dates_across_pages(cli: CliFixture) -> None:
    only_session(cli)
    cli.environment["TZ"] = "Asia/Shanghai"
    cli.write(
        [
            header(timestamp="2025-01-01T00:00:00Z"),
            message("assistant", "一😺\x1b" * 10, stamp="2026-01-14T15:59:00Z"),
            message("assistant", "二😺" * 10, stamp="2026-01-14T16:01:00Z"),
            message("assistant", "未知", stamp="invalid"),
        ]
    )
    other_id = "019c213e-c251-73a3-af66-000000000001"
    write_jsonl(
        cli.source.parent / f"rollout-{other_id}.jsonl",
        [header(other_id), message("user", "outside", stamp="2026-01-13T12:00:00Z")],
    )
    handoff = cli.run(
        "rust", *collect_args("2026-01-15", "2026-01-15"), "--emit-prompt", "--query", "provider:codex limit:1"
    )
    assert handoff.returncode == 0, handoff.stderr
    envelopes = [json.loads(line) for line in handoff.stdout.splitlines() if line.startswith('{"untrusted_data"')]
    task, session = [json.loads(item["content"]) for item in envelopes]
    assert task["date_basis"] == "text_span_local_date" and task["session_count"] == 1
    assert "date" not in session
    assert task["undated_session_count"] == 1
    assert task["undated_sessions"] == [f"codex://{IDENTITY}"]
    assert other_id not in handoff.stdout
    args = [f"codex://{IDENTITY}", "--read", "--order", "asc", "--max-chars", "7", "--json"]
    texts: dict[str | None, str] = {}
    while True:
        result = cli.run("rust", *args)
        assert result.returncode == 0, result.stderr
        page = json.loads(result.stdout)
        for fragment in page["data"]["messages"]:
            for span in fragment["text_spans"]:
                start, end = span["start"] - fragment["start"], span["end"] - fragment["start"]
                assert 0 <= start < end <= len(fragment["text"])
                date = span["date"]
                texts[date] = texts.get(date, "") + fragment["text"][start:end]
        if not page["has_more"]:
            break
        args = [f"codex://{IDENTITY}", "--read", "--cursor", page["data"]["next_cursor"], "--json"]
    assert texts == {"2026-01-14": "一😺" * 10, "2026-01-15": "二😺" * 10, None: "未知"}


def test_cursor_inferred_times_are_not_activity_dates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_cursor import cursor, put

    cli = cursor(tmp_path, monkeypatch)
    put(cli, "bubbleId:parent:c-undated", {"type": 2, "text": "undated answer"})
    put(cli, "composerData:child", {"name": "Child", "createdAt": 1768478400000})
    put(cli, "bubbleId:child:a", {"type": 2, "text": "child undated"})
    put(cli, "bubbleId:child:b", {"type": 2, "text": "child dated", "createdAt": "2026-01-15T12:00:00Z"})
    put(
        cli,
        "bubbleId:parent:d-task",
        {
            "type": 2,
            "toolFormerData": {"name": "task_v2", "additionalData": {"subagentComposerId": "child"}},
        },
    )
    read = cli.run("rust", "cursor://request-parent", "--read", "--json")
    assert read.returncode == 0, read.stderr
    fragments = json.loads(read.stdout)["data"]["messages"]
    unknown = next(item for item in fragments if item["text"] == "undated answer")
    assert all(span["date"] is None for span in unknown["text_spans"])
    known = next(item for item in fragments if item["text"] == "prompt")
    assert all(span["date"] is not None for span in known["text_spans"])
    child = next(item for item in fragments if "child undated" in item["text"])
    assert [span["date"] is None for span in child["text_spans"]] == [True, False]
