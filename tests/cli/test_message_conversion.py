"""Record conversion failures preserve healthy messages, state and warning order."""

import json

from cli_fixture import IDENTITY, header, message, record
import pytest
from test_claude import create as create_claude, event, result, tool
from test_pi import create as create_pi, message as pi_message

pytestmark = pytest.mark.differential


def claude_stream(cli, value):
    return create_claude(
        cli,
        [
            event("user", "Keep"),
            event("assistant", [{"type": "text", "text": "Before"}, tool()], identity="owner"),
            *[event(role, "ignored", message=value) for role in ("assistant", "user", "tool_result")],
            event("user", [result(identity="", content="Tool result")], sourceToolAssistantUUID="owner"),
            event("assistant", [{"type": "text", "text": "After"}]),
        ],
    )


def pi_stream(cli, timestamp, location):
    bad = pi_message("assistant", "Discard", timestamp=timestamp)
    records = [pi_message("user", "Keep")]
    if location == "record":
        bad["timestamp"] = bad["message"].pop("timestamp")
        records += [{"type": "ignored", "padding": "x" * (16 * 1024)} for _ in range(21)]
    records += [pi_message("assistant", "Before"), bad, pi_message("assistant", "After")]
    return create_pi(cli, records)


def recovered_export(cli, provider, lang, *, warnings):
    args = (f"{provider}://{IDENTITY}", "--format", "json,md,raw,print", "--output", "exports", "--lang", lang)
    cli.parity(*args, formats=("json", "markdown", "raw"))
    result = cli.run("rust", *args)
    assert len(result.stderr.splitlines()) == warnings
    payload = json.loads(next((cli.root / "exports").rglob("*.json")).read_text())
    texts = [part.get("text") for message in payload["messages"] for part in message["parts"]]
    assert "Before" in texts and "After" in texts and "Discard" not in texts
    return payload


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("value", [None, [], False, 1, 1.5, "bad"])
def test_claude_invalid_message_preserves_assistant_tool_mapping(cli, lang, value):
    claude_stream(cli, value)
    payload = recovered_export(cli, "claude", lang, warnings=3)
    parts = [part for message in payload["messages"] for part in message["parts"] if part["type"] == "tool"]
    assert parts[0]["state"]["output"][0]["text"] == "Tool result"


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("location", ["record", "message"])
@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_pi_timezone_overflow_skips_record_and_keeps_sequence(cli, lang, location, timestamp):
    pi_stream(cli, timestamp, location)
    payload = recovered_export(cli, "pi", lang, warnings=1)
    assert payload["messages"][-1]["id"] == ("pi-26" if location == "record" else "pi-5")


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("provider", ["codex", "pi"])
def test_ignored_shapes_do_not_gain_conversion_warnings(cli, lang, provider):
    if provider == "codex":
        cli.write(
            [
                header(),
                message("user", "Keep"),
                {"type": "response_item", "payload": None},
                {"type": [], "payload": {"type": "ignored"}},
                record("reasoning", summary=[{"type": []}, {"type": {}}]),
                record(None),
                record(True),
                record(1),
                message("assistant", "After"),
            ]
        )
    else:
        create_pi(
            cli,
            [
                pi_message("user", "Keep"),
                {"type": "message", "message": None},
                pi_message("assistant", [{"type": []}, {"type": {}}]),
                pi_message("assistant", "After", timestamp="0001-01-02T00:00:00+01:00"),
                pi_message("assistant", "Invalid year falls back", timestamp="0000-01-01T00:00:00Z"),
            ],
        )
    cli.parity(
        f"{provider}://{IDENTITY}",
        "--format",
        "json,md,raw,print",
        "--output",
        "exports",
        "--lang",
        lang,
        formats=("json", "markdown", "raw"),
    )
    assert cli.run("rust", f"{provider}://{IDENTITY}", "--lang", lang).stderr == ""


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("kind", ["response_item", "unknown"])
@pytest.mark.parametrize("value", [[], {}])
def test_codex_unhashable_payload_in_metadata_is_a_session_failure(cli, lang, kind, value):
    bad = record(value)
    bad["type"] = kind
    cli.write([header(), message("user", "Keep"), bad])
    cli.parity(f"codex://{IDENTITY}", "--head", "--lang", lang, exit_code=1)
    cli.parity(f"codex://{IDENTITY}", "--format", "raw", "--output", "exports", "--lang", lang, exit_code=1)
