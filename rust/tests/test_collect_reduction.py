"""Concurrency, lossless merge fallback and attribution through the public CLI."""

import json
import threading
import time

from cli_fixture import header, message, write_jsonl
import pytest
from test_collect import ARGS, configure, server
from test_config_shortcuts import config_path


@pytest.mark.parametrize("mode", ["pm", "insight"])
@pytest.mark.parametrize("scenario", ["group", "chunks", "partial"])
def test_reduction_and_partial_failures(cli, mode, scenario):
    for path in (cli.root / "sources" / "codex" / "sessions").rglob("*.jsonl"):
        path.unlink()
    count = 9 if scenario == "group" else 3
    for index in range(count):
        identity = f"019c213e-c251-73a3-af66-{index:012}"
        stamp = f"2026-01-15T12:00:{index:02}+00:00"
        texts = [f"request {index} " + "正文" * 1350] * 4 if scenario == "chunks" else [f"request {index}"]
        write_jsonl(
            cli.source.parent / f"rollout-2026-01-15-{identity}.jsonl",
            [header(identity, timestamp=stamp), *[message("user", text, stamp=stamp) for text in texts]],
        )
    fields = ["requests", "decisions", "outcomes"] if mode == "pm" else ["scene", "stuck", "turning"]
    outputs = []
    prompts = []
    for candidate in ["python", "rust"]:
        lock = threading.Lock()
        active = peak = 0

        def respond(body, _, lock=lock):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            prompt = body["messages"][-1]["content"]
            if "response_format" not in body:
                return 200, {"choices": [{"message": {"content": "# Report"}}]}
            envelopes = [json.loads(line) for line in prompt.splitlines() if line.startswith('{"untrusted_data"')]
            if envelopes[0]["untrusted_data"] == "untrusted_derived_summary":
                return 400, {"error": {"message": "merge unavailable"}}
            source = envelopes[0]["source"]
            if scenario == "partial" and "000000000001#" in source:
                return 401, {}
            facts = [f"{source} fact {i}" for i in range(12)]
            text = json.dumps({fields[0]: facts})
            return 200, {"choices": [{"message": {"content": text}}]}

        with server(respond) as (url, requests):
            configure(cli, url)
            path = config_path(cli)
            path.write_text(path.read_text().replace("summary_concurrency=1", "summary_concurrency=2"))
            result = cli.run(candidate, *ARGS, "--collect-mode", mode, "--save", "report.md", "--lang", "en")
            assert result.returncode == 0, result.stdout + result.stderr
            assert peak == 2
            outputs.append((result.stdout, (cli.root / "report.md").read_text()))
            prompts.append(sorted(body["messages"][-1]["content"] for _, _, body in requests))
            final_prompt = requests[-1][2]["messages"][-1]["content"]
            if scenario == "partial":
                assert "1 session" in result.stderr
                assert "000000000001" not in final_prompt
            if scenario == "chunks":
                assert "chunk-4" in final_prompt
    assert prompts[0] == prompts[1]
    assert outputs[0] == outputs[1]
