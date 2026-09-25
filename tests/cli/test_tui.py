"""A few real PTY tests cover restoration, selection, resizing and secret input."""

from contextlib import contextmanager
import os
import select
import struct
import subprocess
import time

from cli_fixture import RUST
import pytest
from test_config_shortcuts import config_path

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX PTY boundary; portable drawing tested in Rust")


@contextmanager
def terminal(cli, *args, width=80, height=24, stdout_pipe=False):
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
        stdout=subprocess.PIPE if stdout_pipe else slave,
        stderr=slave,
        start_new_session=True,
    )
    output = bytearray()

    def expect(text):
        deadline = time.monotonic() + 12
        expected = text.encode()
        start = 0
        while expected not in output[start:]:
            assert time.monotonic() < deadline, output.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            elif process.poll() is not None:
                pytest.fail(output.decode(errors="replace"))

    def send(text):
        os.write(master, text.encode())

    def resize(columns, lines):
        import signal

        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", lines, columns, 0, 0))
        process.send_signal(signal.SIGWINCH)

    def finish():
        deadline = time.monotonic() + 12
        while process.poll() is None or select.select([master], [], [], 0)[0]:
            assert time.monotonic() < deadline, output.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
        assert termios.tcgetattr(slave) == original
        if not stdout_pipe:
            assert b"\x1b[?1049l" in output
        elif process.stdout is not None:
            output.extend(process.stdout.read())
            process.stdout.close()
        assert b"\x1b[?2004l" in output
        return process.returncode, output.decode(errors="replace")

    try:
        yield expect, send, resize, finish
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("lang,cancel", [("en", "q"), ("zh", "Q"), ("en", "\x03")])
def test_cancel_restores_terminal(cli, lang, cancel):
    with terminal(cli, "--interactive", "-d", "36500", "--lang", lang) as (expect, send, _, finish):
        expect("Codex")
        send(cancel)
        code, output = finish()
        assert code == 1
        assert not (cli.root / "sessions").exists()


def test_resize_narrow_window_and_multiselect(cli):
    with terminal(
        cli,
        "--interactive",
        "-q",
        "provider:codex",
        "-d",
        "36500",
        "--output",
        "exports",
        "--lang",
        "en",
        width=24,
        height=8,
    ) as (expect, send, resize, finish):
        expect("[ ]")
        resize(100, 30)
        expect("00000")
        send("\x1b[F \x1b[H \r")
        code, _ = finish()
        assert code == 0
    assert len(list((cli.root / "exports" / "codex").glob("*.json"))) == 2


def test_config_paste_mask_and_save(cli):
    secret = "unique-private-q-Key-🔒"  # noqa: S105
    with terminal(cli, "--config", "edit", "--lang", "en") as (expect, send, _, finish):
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


def test_cancel_configuration_leaves_file_unchanged(cli):
    path = config_path(cli)
    original = '[export]\noutput="existing"\n'
    path.write_text(original)
    with terminal(cli, "--config", "edit", "--lang", "en") as (expect, send, _, finish):
        expect("OpenAI")
        send("\r")
        expect("Base URL")
        send("\x03")
        code, _ = finish()
        assert code == 1
    assert path.read_text() == original


def test_secret_is_not_echoed_when_stdout_is_redirected(cli):
    secret = "synthetic-redirected-secret"  # noqa: S105
    with terminal(cli, "--config", "edit", "--lang", "en", stdout_pipe=True) as (expect, send, _, finish):
        send("1\nhttp://localhost:9999/v1\nfixture-model\n")
        expect("API Key")
        send(secret + "\r")
        expect("\x1b[?2004l")
        send("exports\ny\n")
        code, output = finish()
        assert code == 0
        assert secret not in output
    import tomli as tomllib

    assert tomllib.loads(config_path(cli).read_text())["ai"]["api_key"] == secret
