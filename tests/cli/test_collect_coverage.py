"""Complete collect input coverage with bounded local model requests."""

import json

from cli_fixture import CliFixture, header, message, write_jsonl
from test_collect import ARGS, configure, only_session, server


def test_long_unicode_message_and_late_outcome_are_fully_processed(cli: CliFixture) -> None:
    only_session(cli)
    body = "完整正文😺" * 9000 + "最后的请求"
    outcome = "最后的结果已经验证"
    cli.write([header(), message("user", body), message("assistant", outcome)])
    events: list[str] = []
    merges: list[int] = []

    def respond(payload: dict, count: int) -> tuple[int, dict]:
        prompt = payload["messages"][-1]["content"]
        assert len(prompt) <= 64000
        envelopes = [json.loads(line) for line in prompt.splitlines() if line.startswith('{"untrusted_data"')]
        if "response_format" not in payload:
            text = "# Complete report"
        elif envelopes[0]["untrusted_data"] == "untrusted_derived_summary":
            merges.append(len(envelopes))
            text = json.dumps({"requests": [f"merged {count} fact {index}" for index in range(12)]})
        else:
            event = envelopes[1]
            assert event["length"] == len(event["content"]) <= 3200
            events.extend(line.split(" text=", 1)[1] for line in event["content"].splitlines())
            text = json.dumps({"requests": [f"chunk {count} fact {index}" for index in range(12)]})
        return 200, {"choices": [{"message": {"content": text}}]}

    before = cli.fixtures.source_manifest(cli.root)
    with server(respond) as (url, _):
        configure(cli, url)
        result = cli.run(*ARGS, "--save", "report.md")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "".join(events) == body + outcome
    assert len(events) > 8 and len(merges) > 1 and max(merges) <= 8
    assert (cli.root / "report.md").read_text() == "# Complete report"
    assert cli.fixtures.source_manifest(cli.root) == before


def test_failed_chunk_lists_omitted_session(cli: CliFixture) -> None:
    only_session(cli)
    cli.write([header(), message("user", "source " * 3000)])
    identity = "019c213e-c251-73a3-af66-000000000001"
    write_jsonl(cli.source.parent / f"rollout-{identity}.jsonl", [header(identity), message("user", "healthy")])

    def respond(payload: dict, _: int) -> tuple[int, dict]:
        prompt = payload["messages"][-1]["content"]
        if "000000000000#chunk-2/events" in prompt:
            return 401, {}
        text = json.dumps({"requests": ["healthy fact"]}) if "response_format" in payload else "# Partial"
        return 200, {"choices": [{"message": {"content": text}}]}

    with server(respond) as (url, _):
        configure(cli, url)
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    report = (cli.root / "report.md").read_text()
    assert "This report is incomplete" in report
    assert "summary failures: 1; sessions included: 1" in report
    assert "> - codex://019c213e-c251-73a3-af66-000000000000" in report
    assert f"> - codex://{identity}" not in report
    assert "chunk 2/" in result.stderr
