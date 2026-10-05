"""Reader input/output contracts and real terminal restoration."""

import base64
import json
import os

from cli_fixture import IDENTITY, call, header, message, output
import pytest
from test_tui import terminal


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_reader_requires_terminal(cli, lang):
    result = cli.run("rust", "--browse", "--lang", lang)
    assert result.returncode == 1
    assert "--browse" in result.stderr
    assert not (cli.root / "sessions").exists()


@pytest.mark.skipif(os.name == "nt", reason="Real PTY; portable rendering is covered by Rust tests")
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_reader_search_copy_export_resize_and_restore(cli, lang):
    cli.write(
        [
            header(),
            message("user", "reader-first"),
            message("assistant", "intro\n" * 40 + "reader-needle"),
            call(arguments={"cmd": "tool-secret-marker"}),
            output("tool completed"),
        ]
    )
    before = cli.fixtures.source_manifest(cli.root)
    with terminal(
        cli,
        "--browse",
        "agents:///project?providers=codex&q=reader-first",
        "-d",
        "36500",
        "--lang",
        lang,
        "--output",
        "exports",
        width=100,
    ) as (expect, send, resize, finish):
        expect("reader-first")
        send("/reader-needle\r")
        expect("needle")
        send("/tool-secret-marker\r")
        expect("tool-secret-marker")
        send("y")
        expect("\x1b]52;c;" + base64.b64encode(f"codex://{IDENTITY}".encode()).decode())
        send("e")
        expect("exports")
        resize(40, 12)
        send("\t\t")
        send("q")
        code, transcript = finish()
        assert code == 0, transcript
        assert "ignored" not in transcript and "忽略" not in transcript
    files = list((cli.root / "exports" / "codex").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["id"] == IDENTITY
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="Real PTY; portable rendering is covered by Rust tests")
def test_reader_next_match_after_resize(cli):
    cli.write(
        [
            header(),
            message("user", "navigation-start"),
            message("assistant", "intro\n" * 40 + "needle FIRST_UNSEEN"),
            message("user", "gap\n" * 40 + "needle SECOND_UNSEEN"),
        ]
    )
    before = cli.fixtures.source_manifest(cli.root)
    with terminal(
        cli,
        "--browse",
        "agents:///project?providers=codex&q=navigation-start",
        "--days",
        "36500",
        "--lang",
        "en",
        width=100,
    ) as (expect, send, resize, finish):
        expect("navigation-start")
        send("/needle\r")
        expect("FIRST_UNSEEN")
        resize(40, 12)
        send("n")
        expect("SECOND_UNSEEN")
        send("q")
        code, transcript = finish()
        assert code == 0, transcript
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="Real PTY; portable rendering is covered by Rust tests")
def test_reader_switch_session_and_ctrl_c(cli):
    with terminal(cli, "--browse", "-q", "provider:codex", "-d", "36500", "--lang", "en", width=100) as (
        expect,
        send,
        _,
        finish,
    ):
        expect("Sessions")
        send("\x1b[Fy")
        expect("\x1b]52;c;" + base64.b64encode(f"codex://{IDENTITY}".encode()).decode())
        send("\x03")
        code, _ = finish()
        assert code == 0
    assert not (cli.root / "sessions").exists()


@pytest.mark.parametrize("extra", [["--search", "needle"], ["--search", "needle", "--json"]])
def test_browse_search_routes_to_reader(cli, extra):
    result = cli.run("rust", "--browse", *extra, "--lang", "en")
    assert result.returncode == 1
    assert not result.stdout
    assert "--browse" in result.stderr or "--json" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY; portable excerpt behavior is covered by Rust tests")
def test_search_preview_export_and_recover_empty_results(cli):
    from cli_fixture import write_jsonl
    from test_collect import only_session

    only_session(cli)
    records = [
        header(),
        message("user", "outside-before"),
        message("assistant", "context-before"),
        message("user", "needle-hit warning-hit"),
        message("assistant", "needle-assistant-ignored"),
        message("user", "warning-hit"),
        message("assistant", "outside-after"),
    ]
    cli.write(records)
    other = "019c213e-c251-73a3-af66-000000000001"
    write_jsonl(cli.source.parent / f"rollout-{other}.jsonl", [header(other), message("user", "second-session-target")])
    before = cli.fixtures.source_manifest(cli.root)
    with terminal(
        cli,
        "--browse",
        "--search",
        "needle warning",
        "--query",
        "provider:codex role:user path:/project",
        "--days",
        "36500",
        "--format",
        "json,markdown",
        "--output",
        "excerpts",
        "--lang",
        "en",
        width=120,
    ) as (expect, send, resize, finish):
        expect("needle-hit")
        expect("words):")
        send("x---e")
        expect("context [json]")
        send("sno-such-evidence\r")
        expect("No matching sessions")
        send("?")
        expect("Provider: codex")
        send("?c")
        expect("search · x")
        send("ssecond-session-target\r")
        expect("second-session-target")
        resize(40, 16)
        send("\ry")
        expect("\x1b]52;c;" + base64.b64encode(f"codex://{other}".encode()).decode())
        send("q")
        code, transcript = finish()
        assert code == 0, transcript
        assert "ignored options" not in transcript
    exported = json.loads((cli.root / "excerpts" / "codex" / f"{IDENTITY}.messages-3-3.json").read_text())
    assert exported["data"]["start"] == exported["data"]["end"] == 3
    assert exported["data"]["uri"] == f"codex://{IDENTITY}"
    markdown = (cli.root / "excerpts" / "codex" / f"{IDENTITY}.messages-3-3.md").read_text()
    assert "needle-hit" in markdown and "outside-before" not in markdown and "needle-assistant-ignored" not in markdown
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY boundary")
def test_initial_empty_search_can_be_changed_without_restarting(cli):
    from test_collect import only_session

    only_session(cli)
    cli.write([header(), message("user", "recoverable-target")])
    with terminal(
        cli,
        "--browse",
        "--search",
        "nothing-here",
        "--query",
        "provider:codex",
        "--days",
        "36500",
        "--lang",
        "en",
        width=40,
    ) as (expect, send, _, finish):
        expect("No matching sessions")
        send("\x1b[Fy")
        send("srecoverable-target\r")
        expect("recoverable-target")
        send("\rx---e")
        expect("context [json]")
        send("q")
        code, transcript = finish()
        assert code == 0, transcript
    assert (cli.root / "sessions" / "codex" / f"{IDENTITY}.messages-1-1.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY boundary")
def test_excerpt_export_rejects_a_changed_source(cli):
    from test_collect import only_session

    only_session(cli)
    cli.write([header(), message("user", "stable-match")])
    with terminal(
        cli,
        "--browse",
        "--search",
        "stable-match",
        "--query",
        "provider:codex",
        "--days",
        "36500",
        "--output",
        "stale-excerpts",
        "--lang",
        "en",
        width=120,
    ) as (expect, send, _, finish):
        expect("stable-match")
        send("x")
        expect("Excerpt #")
        cli.write([header(), message("user", "changed-message-with-different-size")])
        before = cli.fixtures.source_manifest(cli.root)
        send("e")
        expect("no longer matches this transcript")
        send("q")
        code, transcript = finish()
        assert code == 0, transcript
    assert not (cli.root / "stale-excerpts").exists()
    assert cli.fixtures.source_manifest(cli.root) == before
