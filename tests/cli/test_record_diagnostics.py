"""Recoverable record warnings match Python without changing source or export bytes."""

import json
import sqlite3

from cli_fixture import IDENTITY, header, message
import pytest
from sqlite_fixture import NOW, create_legacy
from test_claude import create as create_claude, event
from test_kimi import create as create_kimi, wire_event
from test_pi import create as create_pi, message as pi_message
from test_sqlite_legacy import PROVIDERS

JSONL_PROVIDERS = ("codex", "claude", "kimi-context", "kimi-wire", "pi")


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
    return source, original.count(b"\n") + 2


@pytest.mark.parametrize("provider", JSONL_PROVIDERS)
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_jsonl_warning_text_counts_and_bounded_line_samples(cli, provider, lang):
    source, first_bad_line = damaged_source(cli, provider)
    scheme = provider.split("-")[0]
    args = (f"{scheme}://{IDENTITY}", "--format", "json,md,raw,print", "--output", "exports", "--lang", lang)
    cli.parity(*args, formats=("json", "markdown", "raw"))
    result = cli.run("rust", *args)
    warnings = result.stderr.splitlines()
    assert len(warnings) == {"kimi-context": 2, "kimi-wire": 3}.get(provider, 1)
    samples = ", ".join(str(line) for line in range(first_bad_line, first_bad_line + 5))
    assert all(samples in warning and str(source) in warning for warning in warnings)
    assert next((cli.root / "exports").rglob("*.jsonl")).read_bytes() == source.read_bytes()
    payload = json.loads(next((cli.root / "exports").rglob("*.json")).read_text())
    assert payload["stats"]["message_count"] == 2


@pytest.mark.parametrize("provider", JSONL_PROVIDERS)
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_jsonl_head_list_and_raw_do_not_emit_body_warnings(cli, provider, lang):
    damaged_source(cli, provider)
    scheme = provider.split("-")[0]
    for args, formats in [
        ((f"{scheme}://{IDENTITY}", "--head"), ()),
        (("--list", "-d", "36500", "-q", f"provider:{scheme}"), ()),
        ((f"{scheme}://{IDENTITY}", "--format", "raw", "--output", "exports"), ("raw",)),
    ]:
        cli.parity(*args, "--lang", lang, formats=formats)
        assert cli.run("rust", *args, "--lang", lang).stderr == ""


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_codex_title_index_skips_bad_records_without_body_warning(cli, lang):
    index = cli.root / "sources/codex/session_index.jsonl"
    index.write_bytes(b"[]\nbad\n" + json.dumps({"id": IDENTITY, "thread_name": "Indexed title"}).encode() + b"\n")
    cli.parity(f"codex://{IDENTITY}", "--head", "--lang", lang)
    result = cli.run("rust", f"codex://{IDENTITY}", "--head", "--lang", lang)
    assert result.stderr == ""
    assert "Indexed title" in result.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("formats", ["json,md,raw,print", "raw"])
def test_sqlite_bad_records_keep_healthy_content_and_exact_warnings(cli, provider, lang, formats):
    source = create_legacy(cli, provider)
    with sqlite3.connect(source) as connection:
        for index, data in enumerate(("bad", "[]", b"\xff", b'{"role":"user"}', None, 7.0)):
            identity = f"bad-{index}\n\x1b[31m\u202e"
            connection.execute("INSERT INTO message VALUES (?, 'ses_old', ?, ?)", (identity, NOW + 20 + index, data))
            connection.execute("INSERT INTO part VALUES (?, 'msg_user', ?, ?)", (identity, NOW + 20 + index, data))
    cli.parity("--list", "-d", "36500", "-q", f"provider:{provider}", "--lang", lang)
    cli.parity(f"{provider}://ses_old", "--head", "--lang", lang)
    args = (f"{provider}://ses_old", "--format", formats, "--output", "exports", "--lang", lang)
    expected = ("raw-json",) if formats == "raw" else ("json", "markdown", "raw-json")
    cli.parity(*args, formats=expected)
    result = cli.run("rust", *args)
    assert len(result.stderr.splitlines()) == 12
    assert "\x1b" not in result.stderr and "\u202e" not in result.stderr
    payload = json.loads((cli.root / "exports" / provider / "ses_old.raw.json").read_text())
    assert payload["stats"]["message_count"] == 3
    assert payload["messages"][0]["parts"][0]["text"] == "Prompt"
