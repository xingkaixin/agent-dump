"""Execute collect handoff commands through complete paginated reads."""

import json
import os
from pathlib import Path
import shlex
import subprocess

from cli_fixture import IDENTITY, RUST, CliFixture, header, message, reasoning, write_jsonl
import pytest
from test_collect import ARGS, only_session


def test_handoff_commands_read_every_fragment(cli: CliFixture) -> None:
    only_session(cli)
    body = "完整正文😺" * 6000 + "最后的请求"
    outcome = "最终结果已经验证"
    cli.write([header(), message("user", body), reasoning("private reasoning"), message("assistant", outcome)])
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(*ARGS, "--emit-prompt", "--save", "report.md")
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip().endswith("<!-- agent-dump:collect-manifest-end -->")
    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"untrusted_data"')]
    assert [item["untrusted_data"] for item in envelopes] == ["collect_task", "collect_session"]
    assert all(item["length"] == len(item["content"]) for item in envelopes)
    task, record = [json.loads(item["content"]) for item in envelopes]
    assert task["session_count"] == 1
    assert task["query"] == {
        "providers": ["codex"],
        "path": None,
        "roles": None,
        "keyword": None,
        "limit": None,
    }
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


def _parse_task(prompt_text: str) -> dict:
    assert prompt_text.rstrip().endswith("<!-- agent-dump:collect-manifest-end -->")
    envelopes = [json.loads(line) for line in prompt_text.splitlines() if line.startswith('{"untrusted_data"')]
    assert envelopes[0]["untrusted_data"] == "collect_task"
    return json.loads(envelopes[0]["content"])


def test_emit_prompt_output_writes_file_and_directory_and_records_query(cli: CliFixture) -> None:
    only_session(cli)
    cli.write([header(), message("user", "alpha topic"), message("assistant", "done")])
    before = cli.fixtures.source_manifest(cli.root)

    file_target = cli.root / "out" / "handoff-prompt.txt"
    result = cli.run(
        "--collect",
        "--since",
        "2026-01-15",
        "--until",
        "2026-01-15",
        "--emit-prompt",
        "--output",
        str(file_target),
        "--lang",
        "en",
    )
    assert result.returncode == 0, result.stderr
    task_unscoped = _parse_task(file_target.read_text(encoding="utf-8"))
    assert task_unscoped["query"] is None
    assert task_unscoped["session_count"] > 1
    assert result.stdout == f"✅ Collect prompt saved ({task_unscoped['session_count']} sessions): {file_target}\n"

    existing_dir = cli.root / "prompt-dir"
    existing_dir.mkdir()
    dir_result = cli.run(
        "--collect",
        "--since",
        "2026-01-15",
        "--until",
        "2026-01-15",
        "-q",
        "alpha provider:codex role:user path:/project limit:5",
        "--emit-prompt",
        "--output",
        str(existing_dir),
        "--lang",
        "en",
    )
    assert dir_result.returncode == 0, dir_result.stderr
    default_file = existing_dir / "agent-dump-collect-prompt-20260115-20260115.txt"
    assert default_file.is_file()
    assert dir_result.stdout == f"✅ Collect prompt saved (1 sessions): {default_file.resolve()}\n"
    task = _parse_task(default_file.read_text(encoding="utf-8"))
    expected_path = str(Path(f"{cli.root.drive}/project"))
    assert task["query"] == {
        "providers": ["codex"],
        "path": expected_path,
        "roles": ["user"],
        "keyword": "alpha",
        "limit": 5,
    }

    trailing_result = cli.run(*ARGS, "--emit-prompt", "-output", "trailing-dir/", "--lang", "en")
    assert trailing_result.returncode == 0, trailing_result.stderr
    assert (cli.root / "trailing-dir" / "agent-dump-collect-prompt-20260115-20260115.txt").is_file()
    assert cli.fixtures.source_manifest(cli.root) == before


def test_emit_prompt_output_skips_file_when_empty(cli: CliFixture) -> None:
    only_session(cli)
    cli.write([header(), message("user", "outside range")])
    target = cli.root / "should-not-exist" / "empty-prompt.txt"
    result = cli.run(
        "--collect",
        "--since",
        "2026-02-01",
        "--until",
        "2026-02-01",
        "-q",
        "provider:codex",
        "--emit-prompt",
        "--output",
        str(target),
        "--lang",
        "en",
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
    assert "No sessions found in range 2026-02-01 ~ 2026-02-01." in result.stderr
    assert not target.exists() and not target.parent.exists()


@pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires privileges on Windows")
def test_emit_prompt_output_rejects_source_root_and_symlink_targets(cli: CliFixture) -> None:
    only_session(cli)
    cli.write([header(), message("user", "hello")])
    before = cli.fixtures.source_manifest(cli.root)

    in_source = cli.root / "sources" / "codex" / "prompt.txt"
    source_fail = cli.run(*ARGS, "--emit-prompt", "--output", str(in_source), "--lang", "en")
    assert source_fail.returncode == 1
    assert not source_fail.stdout
    assert "Failed to write collect output" in source_fail.stderr
    assert not in_source.exists()

    sentinel = cli.root / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    symlink_file = cli.root / "prompt-link.txt"
    symlink_file.symlink_to(sentinel)
    link_fail = cli.run(*ARGS, "--emit-prompt", "--output", str(symlink_file), "--lang", "en")
    assert link_fail.returncode == 1
    assert not link_fail.stdout
    assert "symlink" in link_fail.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"

    prompt_dir = cli.root / "dir-with-link"
    prompt_dir.mkdir()
    (prompt_dir / "agent-dump-collect-prompt-20260115-20260115.txt").symlink_to(sentinel)
    dir_link_fail = cli.run(*ARGS, "--emit-prompt", "--output", str(prompt_dir), "--lang", "en")
    assert dir_link_fail.returncode == 1
    assert not dir_link_fail.stdout
    assert "symlink" in dir_link_fail.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert cli.fixtures.source_manifest(cli.root) == before


def test_emit_prompt_throttles_scan_progress_for_many_sessions(cli: CliFixture) -> None:
    only_session(cli)
    session_dir = Path(cli.source).parent
    cli.source.unlink()
    total = 65
    for index in range(total):
        identity = f"019c213e-c251-73a3-af66-{index:012d}"
        write_jsonl(
            session_dir / f"rollout-{identity}.jsonl",
            [header(identity), message("user", f"session {index}")],
        )
    result = cli.run(*ARGS, "--emit-prompt", "--lang", "en")
    assert result.returncode == 0, result.stderr
    assert _parse_task(result.stdout)["session_count"] == total
    progress_lines = [line for line in result.stderr.splitlines() if line.startswith("Scanning sessions: ")]
    assert progress_lines == ["Scanning sessions: 0/65", "Scanning sessions: 50/65", "Scanning sessions: 65/65"]
