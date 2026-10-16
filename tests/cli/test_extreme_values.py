"""Provider numeric boundaries remain observable through exported data."""

from cli_fixture import IDENTITY, header, message, provider_export
import pytest
from test_claude import create as claude_create, event
from test_kimi import create as kimi_create
from test_pi import create as pi_create, message as pi_message

pytestmark = pytest.mark.differential


@pytest.mark.parametrize("provider", ["claude"])
@pytest.mark.parametrize("value", [2**63 - 1, 2**80, -(2**80), str(2**100), 1e100, "  +1_234  ", "١٢٣", "１２３"])
def test_large_token_values_are_preserved_and_accumulated(cli, provider, value):
    if provider == "claude":
        cli_event = event("assistant", [{"type": "text", "text": "Numbers"}])
        cli_event["message"]["usage"] = {"input_tokens": value, "output_tokens": value}
        claude_create(cli, [event("user", "Numbers"), cli_event, event("user", "Next"), cli_event])
    payload = provider_export(cli, f"{provider}://{IDENTITY}", "claudecode" if provider == "claude" else provider)
    assert payload["stats"]["total_input_tokens"] == int(value) * 2


@pytest.mark.parametrize("provider", ["codex", "claude", "kimi"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_json_numbers_preserve_messages_and_default_statistics(cli, provider, value):
    if provider == "codex":
        item = message("user", "Numbers")
        item["payload"]["content"][0]["text"] = {"value": value, "literal": "NaN Infinity"}
        cli.write(
            [header(), item, {"type": "event_msg", "payload": {"info": {"total_token_usage": {"input_tokens": value}}}}]
        )
    elif provider == "claude":
        item = event("assistant", [{"type": "text", "text": "Numbers"}])
        item["message"]["usage"] = {"input_tokens": value}
        claude_create(cli, [event("user", "Numbers"), item])
    else:
        kimi_create(
            cli,
            context=[{"role": "user", "content": "Numbers"}, {"role": "_usage", "token_count": value}],
            wire=[{"message": {"usage": {"input_tokens": value}}}],
        )
    payload = provider_export(cli, f"{provider}://{IDENTITY}", "claudecode" if provider == "claude" else provider)
    assert payload["stats"]["total_input_tokens"] == 0


def test_float_overflow_and_nan_do_not_collide_with_literals(cli):
    from test_kimi import call

    kimi_create(
        cli,
        context=[
            {
                "role": "assistant",
                "tool_calls": [
                    call(arguments='{"nan":NaN,"positive":1e9999,"negative":-1e9999,"literal":"1e9999 NaN"}')
                ],
            }
        ],
    )
    provider_export(cli, f"kimi://{IDENTITY}", "kimi")


@pytest.mark.parametrize("value", ["\x85\u00a0\u200b\u2028\ue000\U000f0000", "quote'\"\\\t\n中文😀"])
def test_python_container_string_representation(cli, value):
    item = message("assistant", "placeholder")
    item["payload"]["content"][0]["text"] = {"value": [value]}
    cli.write([header(), message("user", "Unicode"), item])
    provider_export(cli, f"codex://{IDENTITY}", "codex")


@pytest.mark.parametrize("value", [2**80, str(2**100), 1e100, float("nan"), float("inf")])
def test_legacy_sqlite_numeric_boundaries(cli, value):
    import json
    import sqlite3

    from sqlite_fixture import create_legacy, export

    path = create_legacy(cli)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE message SET data = ? WHERE id = 'msg_assistant'",
            (json.dumps({"role": "assistant", "tokens": {"input": value, "output": value}, "cost": value}),),
        )
    export(cli, identity="ses_old")


@pytest.mark.parametrize("value", [2**80, "  +1_234  ", float("inf")])
def test_minimax_token_boundaries(tmp_path, monkeypatch, value):
    from desktop_fixture import desktop, exports
    from test_minimax import add_message

    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    add_message(
        cli,
        {
            "msg_content": "Numbers",
            "usage": {"input_tokens": value, "output_tokens": value, "cache_read": value},
        },
    )
    exports(cli, "minimax", identity)


@pytest.mark.parametrize("provider", ["codex", "claude", "pi"])
@pytest.mark.parametrize("value", [None, 7, False, ["one"], {"path": "work"}])
def test_metadata_values_preserve_payload_and_display_projection(cli, provider, value):
    if provider == "codex":
        cli.write([header(cwd=value, cli_version=value)])
    elif provider == "claude":
        claude_create(cli, [event("system", [], cwd=value, version=value)])
    else:
        pi_create(cli, [pi_message("user", "Keep")], header={"cwd": value, "version": value})
    cli.parity(f"{provider}://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"{provider}://{IDENTITY}", "claudecode" if provider == "claude" else provider)


@pytest.mark.parametrize("provider", ["codex", "claude", "pi"])
@pytest.mark.parametrize(
    "timestamp", ["0001-01-01T00:00:00Z", "9999-12-31T23:59:59.999999Z", "0000-01-01T00:00:00Z", 1e100, None, "invalid"]
)
def test_timestamp_boundaries_keep_reference_fallbacks(cli, provider, timestamp):
    if provider == "codex":
        cli.write([header(timestamp=timestamp), message("user", "Time", stamp=timestamp)])
    elif provider == "claude":
        claude_create(cli, [event("user", "Time", timestamp=timestamp)])
    else:
        pi_create(cli, [pi_message("user", "Time", timestamp=timestamp)], header={"timestamp": timestamp})
    cli.parity(f"{provider}://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"{provider}://{IDENTITY}", "claudecode" if provider == "claude" else provider)
