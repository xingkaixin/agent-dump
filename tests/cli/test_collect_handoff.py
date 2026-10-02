"""Execute collect handoff commands through complete paginated reads."""

import json
import os
import shlex
import subprocess

from cli_fixture import IDENTITY, RUST, CliFixture, header, message, reasoning
import pytest
from test_collect import ARGS, only_session


@pytest.mark.parametrize("mode", ["pm", "insight"])
def test_handoff_commands_read_every_fragment(cli: CliFixture, mode: str) -> None:
    only_session(cli)
    body = "完整正文😺" * 6000 + "最后的请求"
    outcome = "最终结果已经验证"
    cli.write([header(), message("user", body), reasoning("private reasoning"), message("assistant", outcome)])
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", *ARGS, "--emit-prompt", "--collect-mode", mode, "--save", "report.md")
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip().endswith("<!-- agent-dump:collect-manifest-end -->")
    for required in (
        "has_more=false",
        "data.next_cursor=null",
        "status=partial",
        "不混合不同版本",
        "不加 --details",
        "truncated=true",
        "start/end",
        "total_chars",
        "页数预算",
        "丢弃旧版本笔记",
    ):
        assert required in result.stdout
    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"untrusted_data"')]
    assert [item["untrusted_data"] for item in envelopes] == ["collect_task", "collect_session"]
    assert all(item["length"] == len(item["content"]) for item in envelopes)
    task, record = [json.loads(item["content"]) for item in envelopes]
    assert task["session_count"] == 1
    uri = f"codex://{IDENTITY}"
    argv = record["read_argv"]
    assert argv == [str(RUST), uri, "--read", "--order", "asc", "--json"]
    assert record["uri"] == envelopes[1]["source"] == uri
    if os.name != "nt":
        assert shlex.split(record["read_command"]) == argv
    else:
        assert record["read_command"].startswith("& '")
    fragments: dict[int, str] = {}
    cursors: set[str] = set()
    revision = None
    pages = 0
    while True:
        read = subprocess.run(  # noqa: S603
            argv, cwd=cli.root, env=cli.environment, capture_output=True, text=True, encoding="utf-8", timeout=30
        )
        assert read.returncode == 0, read.stderr
        page = json.loads(read.stdout)
        assert page["schema_version"] == 1 and page["kind"] == "read" and page["status"] == "ok"
        data = page["data"]
        assert data["uri"] == uri and data["options"]["order"] == "asc"
        assert revision in (None, data["revision"])
        revision = data["revision"]
        assert sum(len(item["text"]) for item in data["messages"]) <= 12000
        for item in data["messages"]:
            assert item["role"] in ("user", "assistant")
            previous = fragments.get(item["position"], "")
            assert item["start"] == len(previous)
            assert item["end"] == len(previous) + len(item["text"])
            fragments[item["position"]] = previous + item["text"]
        pages += 1
        cursor = data["next_cursor"]
        assert page["has_more"] == (cursor is not None)
        if not page["has_more"]:
            break
        assert cursor and cursor not in cursors
        cursors.add(cursor)
        argv = [str(RUST), uri, "--read", "--cursor", cursor, "--json"]
    assert pages >= 3
    assert "".join(fragments.values()) == body + outcome
    assert cli.fixtures.source_manifest(cli.root) == before
    assert not (cli.root / "report.md").exists()
