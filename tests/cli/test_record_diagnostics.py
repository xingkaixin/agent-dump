"""Recoverable record warnings keep healthy content without changing source or export bytes."""

import json
import os
import sqlite3
import sys

from cli_fixture import IDENTITY, header, message
import pytest
from sqlite_fixture import NOW, create_legacy
from test_claude import create as create_claude, event
from test_kimi import create as create_kimi, wire_event
from test_pi import create as create_pi, message as pi_message

JSONL_PROVIDERS = ("codex", "claude", "kimi-context", "kimi-wire", "pi")
SQLITE_PROVIDERS = [
    "opencode",
    pytest.param(
        "zcode",
        marks=pytest.mark.skipif(
            not sys.platform.startswith(("darwin", "win")), reason="ZCode supports macOS and Windows"
        ),
    ),
]


def damaged_source(cli, provider):
    if provider == "codex":
        cli.write([header(), message("user", "Keep")])
        source = cli.source
    elif provider == "claude":
        source = create_claude(cli, [event("user", "Keep")])
    elif provider == "kimi-context":
        source = create_kimi(cli, context=[{"role": "user", "content": "Keep"}]) / "context.jsonl"
    elif provider == "kimi-wire":
        source = create_kimi(cli, wire=[wire_event("TurnBegin", user_input=[{"text": "Keep"}])]) / "wire.jsonl"
    else:
        source = create_pi(cli, [pi_message("user", "Keep")])
    original = source.read_bytes()
    source.write_bytes(
        original
        + b'\ninvalid\n\xff\n[]\n1\n"text"\nnull\ntrue\n'
        + original.splitlines(keepends=True)[-1]
        + b'{"partial":'
    )
    if provider.startswith("kimi"):
        os.utime(source, (1768478400, 1768478400))
    return source, original.count(b"\n") + 2


@pytest.mark.parametrize("provider", JSONL_PROVIDERS)
def test_jsonl_warning_text_counts_and_bounded_line_samples(cli, provider):
    source, first_bad_line = damaged_source(cli, provider)
    before = cli.fixtures.source_manifest(cli.root)
    scheme = provider.split("-")[0]
    args = (f"{scheme}://{IDENTITY}", "--format", "json,md,raw,print", "--output", "exports", "--lang", "en")
    result = cli.run("rust", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    warnings = result.stderr.splitlines()
    assert len(warnings) == {"kimi-context": 2, "kimi-wire": 3}.get(provider, 1)
    samples = ", ".join(str(line) for line in range(first_bad_line, first_bad_line + 5))
    assert all(samples in warning and str(source) in warning for warning in warnings)
    assert next((cli.root / "exports").rglob("*.jsonl")).read_bytes() == source.read_bytes()
    payload = json.loads(next((cli.root / "exports").rglob("*.json")).read_text())
    assert payload["stats"]["message_count"] == 2
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("provider", SQLITE_PROVIDERS)
def test_sqlite_bad_records_keep_healthy_content_and_sanitized_warnings(cli, provider):
    source = create_legacy(cli, provider)
    with sqlite3.connect(source) as connection:
        for index, data in enumerate(("bad", "[]", b"\xff", b'{"role":"user"}', None, 7.0)):
            identity = f"bad-{index}\n\x1b[31m\u202e"
            connection.execute("INSERT INTO message VALUES (?, 'ses_old', ?, ?)", (identity, NOW + 20 + index, data))
            connection.execute("INSERT INTO part VALUES (?, 'msg_user', ?, ?)", (identity, NOW + 20 + index, data))
    before = cli.fixtures.source_manifest(cli.root)
    args = (f"{provider}://ses_old", "--format", "json,md,raw,print", "--output", "exports", "--lang", "en")
    result = cli.run("rust", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(result.stderr.splitlines()) == 12
    assert "\x1b" not in result.stderr and "\u202e" not in result.stderr
    payload = json.loads((cli.root / "exports" / provider / "ses_old.raw.json").read_text())
    assert payload["stats"]["message_count"] == 3
    assert payload["messages"][0]["parts"][0]["text"] == "Prompt"
    assert cli.fixtures.source_manifest(cli.root) == before
