"""Export boundaries: byte preservation, partial success and source protection."""

import json

from cli_fixture import IDENTITY, header, message
import pytest


@pytest.mark.parametrize("blocked", [(".json",), (".json", ".md", ".raw.jsonl")])
def test_file_export_failures_do_not_stop_other_formats(cli, blocked):
    before = cli.fixtures.source_manifest(cli.root)
    directory = cli.root / "exports" / "codex"
    directory.mkdir(parents=True)
    for suffix in blocked:
        (directory / f"{IDENTITY}{suffix}").mkdir()
    result = cli.run(f"codex://{IDENTITY}", "--format", "json,md,raw", "--output", "exports")
    assert result.returncode == (1 if len(blocked) == 3 else 0), result.stdout + result.stderr
    assert result.stdout.count("Diagnostic\n") == len(blocked)
    assert not result.stderr
    files = sorted(path.name for path in directory.iterdir() if path.is_file())
    assert files == sorted(f"{IDENTITY}{suffix}" for suffix in (".json", ".md", ".raw.jsonl") if suffix not in blocked)
    assert len(list(directory.iterdir())) == 3
    assert cli.fixtures.source_manifest(cli.root) == before


def test_codex_json_stats_sum_each_token_delta_once(cli):
    def usage(total, last):
        def counts(tokens):
            return {
                "input_tokens": tokens,
                "cached_input_tokens": tokens // 2,
                "output_tokens": tokens // 10,
                "total_tokens": tokens + tokens // 10,
            }

        return {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": counts(total), "last_token_usage": counts(last)},
            },
        }

    rate_limits_only = {"type": "event_msg", "payload": {"type": "token_count", "info": None}}
    cli.write([header(), message("user", "Keep"), usage(100, 100), usage(300, 200), usage(300, 200), rate_limits_only])
    result = cli.run(f"codex://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    stats = json.loads((cli.root / "exports" / "codex" / f"{IDENTITY}.json").read_text())["stats"]
    assert (stats["total_input_tokens"], stats["total_output_tokens"], stats["total_cache_read_tokens"]) == (
        300,
        30,
        150,
    )


def test_codex_reply_after_a_closed_plan_stays_a_message(cli):
    cli.write(
        [
            header(),
            message("user", "Plan it"),
            message("assistant", "<proposed_plan>\nStep one\n</proposed_plan>"),
            message("assistant", "Anything to adjust?"),
            message("user", "Use the other approach"),
        ]
    )
    result = cli.run(f"codex://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    messages = json.loads((cli.root / "exports" / "codex" / f"{IDENTITY}.json").read_text())["messages"]
    texts = [part.get("text") for item in messages for part in item["parts"] if part["type"] == "text"]
    assert texts == ["Plan it", "Anything to adjust?", "Use the other approach"]
    plan = next(part for item in messages for part in item["parts"] if part["type"] == "plan")
    assert (plan["approval_status"], plan["output"]) == ("fail", None)
