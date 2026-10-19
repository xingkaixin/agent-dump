"""Qoder and Qoder CN sessions in the Claude Code project layout."""

import json

from cli_fixture import IDENTITY, write_jsonl
import pytest
from test_claude import event, result, tool

PROVIDERS = {
    "qoder": ("QODER_CONFIG_DIR", ".qoder"),
    "qoder-cn": ("QODERCN_CONFIG_DIR", ".qoder-cn"),
}


def create(root, records, *, identity=IDENTITY):
    return write_jsonl(root / "projects/-workspace-qoder" / f"{identity}.jsonl", records)


def listed(cli, provider):
    listing = cli.run("--list", "-d", "36500", "-q", f"provider:{provider}", "--json")
    assert listing.returncode == 0, listing.stderr
    return {item["id"]: item for item in json.loads(listing.stdout)["data"]}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_list_head_and_export_use_the_claude_transcript(cli, provider):
    usage = {"input_tokens": 40, "cache_read_input_tokens": 300, "output_tokens": 25}
    records = [
        event("user", "Explain the cache", identity="prompt", cwd="/workspace/qoder"),
        event("assistant", [tool()], identity="call-owner"),
        event("user", [result()], identity="output"),
    ]
    records[1]["message"].update(model="glm-5", usage=usage)
    source = create(cli.root / "sources" / provider, records)
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli, provider)[IDENTITY]
    assert {key: record[key] for key in ("uri", "title", "working_directory", "model", "message_count")} == {
        "uri": f"{provider}://{IDENTITY}",
        "title": "Explain the cache",
        "working_directory": "/workspace/qoder",
        "model": "glm-5",
        "message_count": 2,
    }
    shown = cli.run(record["uri"], "--head", "--json")
    assert shown.returncode == 0, shown.stderr
    head = json.loads(shown.stdout)["data"]
    assert {key: head[key] for key in record} == record

    exported = cli.run(record["uri"], "--format", "json,raw", "--output", "exports")
    assert exported.returncode == 0, exported.stderr
    exports = cli.root / "exports" / provider
    assert (exports / f"{IDENTITY}.raw.jsonl").read_bytes() == source.read_bytes()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before
    assert payload["stats"]["total_input_tokens"] == 340
    user, assistant = payload["messages"]
    assert user["parts"][0]["text"] == "Explain the cache"
    assert (assistant["agent"], assistant["model"]) == (provider, "glm-5")
    assert assistant["parts"][0]["state"]["status"] == "completed"


def test_default_roots_keep_qoder_and_qoder_cn_apart(cli):
    home = cli.root / "home"
    for provider, (variable, directory) in PROVIDERS.items():
        del cli.environment[variable]
        create(home / directory, [event("user", provider)], identity=provider)

    for provider in PROVIDERS:
        assert {key: item["title"] for key, item in listed(cli, provider).items()} == {provider: provider}
    missing = cli.run("qoder://qoder-cn", "--head")
    assert missing.returncode == 1
