"""A few real PTY tests cover restoration, selection, resizing and secret input."""

import base64
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import os
import select
import sqlite3
import struct
import subprocess
import time
import unicodedata

from cli_fixture import RUST, header, message, write_jsonl
import pytest
from test_config_shortcuts import config_path

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX PTY boundary; portable drawing tested in Rust")


def _render_screen(raw: str, width: int, height: int) -> str:
    grid = [[" "] * width for _ in range(height)]
    row = col = 0
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\x1b":
            if i + 1 < n and raw[i + 1] == "[":
                j = i + 2
                while j < n and not ("@" <= raw[j] <= "~"):
                    j += 1
                if j < n:
                    params = raw[i + 2 : j]
                    cmd = raw[j]
                    if cmd in ("H", "f"):
                        parts = params.split(";")
                        row = max(0, (int(parts[0]) if parts[0] else 1) - 1)
                        col = max(0, (int(parts[1]) if len(parts) > 1 and parts[1] else 1) - 1)
                    elif cmd == "J" and params in ("", "2"):
                        grid = [[" "] * width for _ in range(height)]
                    elif cmd == "K" and 0 <= row < height:
                        for c in range(col, width):
                            grid[row][c] = " "
                i = j + 1
                continue
            if i + 1 < n and raw[i + 1] == "]":
                j = i + 2
                while j < n:
                    if raw[j] == "\x07":
                        j += 1
                        break
                    if raw[j] == "\x1b" and j + 1 < n and raw[j + 1] == "\\":
                        j += 2
                        break
                    j += 1
                i = j
                continue
            i += 2
            continue
        if ch == "\r":
            col = 0
        elif ch == "\n":
            row = min(height - 1, row + 1)
        elif ch >= " ":
            if 0 <= row < height and 0 <= col < width:
                grid[row][col] = ch
            col += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        i += 1
    return "\n".join("".join(line) for line in grid)


@contextmanager
def terminal(cli, *args, width=80, height=24):
    import fcntl
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))
    env = {**cli.environment, "TERM": "xterm-256color"}
    process = subprocess.Popen(  # noqa: S603
        [str(RUST), *args],
        cwd=cli.root,
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    output = bytearray()
    seen = 0

    def expect(text, *, screen=False):
        nonlocal seen
        deadline = time.monotonic() + 12
        expected = text.encode()
        while True:
            if screen:
                rendered = _render_screen(output.decode(errors="replace"), width, height)
                if text in rendered:
                    seen = len(output)
                    return
            else:
                found = output.find(expected, seen)
                if found >= 0:
                    seen = found + len(expected)
                    return
            assert time.monotonic() < deadline, (
                _render_screen(output.decode(errors="replace"), width, height)
                if screen
                else output.decode(errors="replace")
            )
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            elif process.poll() is not None:
                pytest.fail(output.decode(errors="replace"))

    def send(text):
        os.write(master, text.encode())

    def finish():
        deadline = time.monotonic() + 12
        while process.poll() is None or select.select([master], [], [], 0)[0]:
            assert time.monotonic() < deadline, output.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
        assert termios.tcgetattr(slave) == original
        assert b"\x1b[?1049l" in output
        assert b"\x1b[?2004l" in output
        return process.returncode, output.decode(errors="replace")

    try:
        yield expect, send, finish
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        os.close(master)
        os.close(slave)


def test_config_paste_mask_and_save(cli):
    secret = "unique-private-q-Key-🔒"  # noqa: S105
    with terminal(cli, "--config", "edit", "--lang", "en") as (expect, send, finish):
        expect("OpenAI")
        send("\r")
        expect("Base URL")
        send("\x1b[200~http://localhost:9999/v1\x1b[201~\r")
        expect("Model")
        send("\x1b[200~模型-model\x1b[201~\r")
        expect("API Key")
        send(f"\x1b[200~{secret}\x1b[201~\r")
        expect("Default export output")
        send("exports\r")
        expect("Yes")
        send("\r")
        code, output = finish()
        assert code == 0
        assert secret not in output
        assert "unique-private" not in output
    import tomli as tomllib

    value = tomllib.loads(config_path(cli).read_text())
    assert value["ai"]["api_key"] == secret
    assert value["ai"]["model"] == "模型-model"
    assert value["export"]["output"] == "exports"


def test_browse_time_field_created_sorts_and_groups_by_created_time(cli):
    for path in cli.source.parent.glob("*.jsonl"):
        path.unlink()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    sessions = [
        ("newer-created", "CreatedFirst", now - timedelta(days=1), now - timedelta(days=1)),
        ("newer-updated", "UpdatedFirst", now - timedelta(days=3), now),
    ]
    for identity, text, created, updated in sessions:
        path = write_jsonl(
            cli.source.parent / f"rollout-{identity}.jsonl",
            [
                header(identity, timestamp=created.isoformat()),
                message("user", text, stamp=updated.isoformat()),
            ],
        )
        modified = max(created, updated)
        os.utime(path, (modified.timestamp(), modified.timestamp()))

    with terminal(
        cli,
        "--browse",
        "--time-field",
        "created",
        "-d",
        "7",
        "-q",
        "provider:codex",
        "--lang",
        "en",
        width=120,
        height=30,
    ) as (expect, send, finish):
        expect("UpdatedFirst")
        send("y")
        expect("Copy request sent")
        send("q")
        code, output = finish()
        assert code == 0
        expected_uri = base64.b64encode(b"codex://newer-created").decode()
        assert expected_uri in output
        assert "Yesterday" in output
        assert "Today" not in output


def test_browse_copy_message_excerpt_and_refresh_preserves_selection(cli):
    for path in cli.source.parent.glob("*.jsonl"):
        path.unlink()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    alpha_time = now - timedelta(hours=1)
    beta_time = now - timedelta(hours=2)

    alpha_path = write_jsonl(
        cli.source.parent / "rollout-alpha.jsonl",
        [
            header("alpha", timestamp=alpha_time.isoformat()),
            message("user", "AlphaPrompt", stamp=alpha_time.isoformat()),
            message("assistant", "AlphaNeedleReply", stamp=(alpha_time + timedelta(seconds=10)).isoformat()),
        ],
    )
    os.utime(alpha_path, (alpha_time.timestamp(), alpha_time.timestamp()))

    beta_path = write_jsonl(
        cli.source.parent / "rollout-beta.jsonl",
        [
            header("beta", timestamp=beta_time.isoformat()),
            message("user", "BetaPrompt", stamp=beta_time.isoformat()),
        ],
    )
    os.utime(beta_path, (beta_time.timestamp(), beta_time.timestamp()))

    with terminal(
        cli,
        "--browse",
        "--since",
        (now - timedelta(days=2)).date().isoformat(),
        "-q",
        "provider:codex",
        "--lang",
        "en",
        width=140,
        height=30,
    ) as (expect, send, finish):
        expect("AlphaNeedleReply", screen=True)
        send("d")
        expect("The date range is fixed", screen=True)
        send("Y")
        expect("Copy request sent for message #1", screen=True)
        send("/AlphaNeedleReply\r")
        expect("1 matching messages", screen=True)
        send("x")
        expect("Excerpt #1–2 / 2", screen=True)
        send("Y")
        expect("Copy request sent for excerpt #1–2", screen=True)
        send("x")
        send("y")
        expect("Copy request sent", screen=True)

        send("\x1b[D")
        send("j")
        expect("#1 / 1", screen=True)

        gamma_time = now
        gamma_path = write_jsonl(
            cli.source.parent / "rollout-gamma.jsonl",
            [
                header("gamma", timestamp=gamma_time.isoformat()),
                message("user", "GammaNewest", stamp=gamma_time.isoformat()),
            ],
        )
        os.utime(gamma_path, (gamma_time.timestamp(), gamma_time.timestamp()))

        beta_updated = now - timedelta(minutes=5)
        write_jsonl(
            beta_path,
            [
                header("beta", timestamp=beta_time.isoformat()),
                message("user", "BetaPrompt", stamp=beta_time.isoformat()),
                message("assistant", "BetaRefreshedBody", stamp=beta_updated.isoformat()),
            ],
        )
        os.utime(beta_path, (beta_updated.timestamp(), beta_updated.timestamp()))

        send("r")
        expect("Refreshed (3 sessions)", screen=True)
        expect("BetaRefreshedBody", screen=True)
        send("y")
        expect("Copy request sent", screen=True)
        send("q")
        code, output = finish()
        assert code == 0
        assert base64.b64encode(b"AlphaPrompt").decode() in output
        assert base64.b64encode(b"#1 [user]\nAlphaPrompt\n\n#2 [assistant]\nAlphaNeedleReply").decode() in output
        assert base64.b64encode(b"codex://alpha").decode() in output
        assert base64.b64encode(b"codex://beta").decode() in output


def test_browse_provider_and_day_window_cycling(cli):
    for path in cli.source.parent.glob("*.jsonl"):
        path.unlink()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    recent_time = now - timedelta(hours=1)
    older_time = now - timedelta(days=20)

    recent_path = write_jsonl(
        cli.source.parent / "rollout-recent-codex.jsonl",
        [
            header("recent-codex", timestamp=recent_time.isoformat()),
            message("user", "RecentCodexTitle", stamp=recent_time.isoformat()),
        ],
    )
    os.utime(recent_path, (recent_time.timestamp(), recent_time.timestamp()))

    older_path = write_jsonl(
        cli.source.parent / "rollout-older-codex.jsonl",
        [
            header("older-codex", timestamp=older_time.isoformat()),
            message("user", "OlderCodexTitle", stamp=older_time.isoformat()),
        ],
    )
    os.utime(older_path, (older_time.timestamp(), older_time.timestamp()))

    with closing(sqlite3.connect(cli.environment["OPENCODE_DB"])) as connection, connection:
        old_ms = int((now - timedelta(days=200)).timestamp() * 1000)
        recent_ms = int((now - timedelta(hours=2)).timestamp() * 1000)
        connection.execute("UPDATE session_v2 SET time_created = ?, time_updated = ?", (old_ms, old_ms))
        connection.execute(
            "UPDATE session_v2 SET title = 'RecentOpenCodeTitle', time_created = ?, time_updated = ? WHERE id = ?",
            (recent_ms, recent_ms, "ses_bench_000000"),
        )

    with terminal(
        cli,
        "--browse",
        "-d",
        "7",
        "-q",
        "provider:codex,opencode",
        "--lang",
        "en",
        width=140,
        height=30,
    ) as (expect, send, finish):
        expect("RecentCodexTitle", screen=True)
        send("p")
        expect("Provider: opencode (1 sessions)", screen=True)
        send("p")
        expect("Provider: codex (1 sessions)", screen=True)
        send("p")
        expect("Provider: codex,opencode (2 sessions)", screen=True)
        send("d")
        expect("Window: last 30 days (3 sessions)", screen=True)
        expect("OlderCodexTitle", screen=True)
        expect("last 30 days", screen=True)
        send("q")
        code, _output = finish()
        assert code == 0
