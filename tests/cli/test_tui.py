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

    def expect(text):
        nonlocal seen
        deadline = time.monotonic() + 12
        expected = text.encode()
        while (found := output.find(expected, seen)) < 0:
            assert time.monotonic() < deadline, output.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            elif process.poll() is not None:
                pytest.fail(output.decode(errors="replace"))
        seen = found + len(expected)

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
