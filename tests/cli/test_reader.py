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
        expect("reader-needle")
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
