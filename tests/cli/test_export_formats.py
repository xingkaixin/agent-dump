"""Export boundaries: byte preservation, partial success and source protection."""

import json

from cli_fixture import IDENTITY, header, message
import pytest
from test_config_shortcuts import config_path


@pytest.mark.parametrize("blocked", [(".json",), (".json", ".md", ".raw.jsonl")])
def test_file_export_failures_do_not_stop_other_formats(cli, blocked):
    before = cli.fixtures.source_manifest(cli.root)
    directory = cli.root / "exports" / "codex"
    directory.mkdir(parents=True)
    for suffix in blocked:
        (directory / f"{IDENTITY}{suffix}").mkdir()
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json,md,raw", "--output", "exports")
    assert result.returncode == (1 if len(blocked) == 3 else 0), result.stdout + result.stderr
    assert result.stdout.count("Diagnostic\n") == len(blocked)
    assert not result.stderr
    files = sorted(path.name for path in directory.iterdir() if path.is_file())
    assert files == sorted(f"{IDENTITY}{suffix}" for suffix in (".json", ".md", ".raw.jsonl") if suffix not in blocked)
    assert len(list(directory.iterdir())) == 3
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("output_format", ["markdown", "raw"])
def test_new_export_formats_cannot_write_into_source(cli, output_format):
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(
        "rust", f"codex://{IDENTITY}", "--format", output_format, "--output", str(cli.root / "sources" / "codex")
    )
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


def test_configured_output_applies_to_every_file_format(cli):
    cli.write([header(), message("user", "Keep")])
    config_path(cli).write_text('[export]\noutput = "configured"\n')
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json,md,raw", "--lang", "en")
    assert result.returncode == 0, result.stderr
    exported = sorted(p.name for p in (cli.root / "configured" / "codex").iterdir())
    assert exported == sorted(f"{IDENTITY}{suffix}" for suffix in (".json", ".md", ".raw.jsonl"))
    assert not (cli.root / "sessions").exists()


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
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    stats = json.loads((cli.root / "exports" / "codex" / f"{IDENTITY}.json").read_text())["stats"]
    assert (stats["total_input_tokens"], stats["total_output_tokens"], stats["total_cache_read_tokens"]) == (
        300,
        30,
        150,
    )
