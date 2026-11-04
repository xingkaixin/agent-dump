"""Kimi context and legacy wire contracts through the published CLI surface."""

import hashlib
import json
import os

from cli_fixture import IDENTITY, write_jsonl


def create(cli, *, context=None, wire=None, metadata=None, cwd="/workspace/kimi"):
    root = cli.root / "sources/kimi"
    project = hashlib.md5(cwd.encode(), usedforsecurity=False).hexdigest() if cwd else "unresolved-project"
    directory = root / "sessions" / project / IDENTITY
    directory.mkdir(parents=True, exist_ok=True)
    (root / "kimi.json").write_text(json.dumps({"work_dirs": [{"path": cwd}]}))
    path = directory / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "session_id": IDENTITY,
                "title": " Kimi  会话 ",
                "createdAt": 1768478400000,
                "wire_mtime": 1768478400,
                **(metadata or {}),
            }
        )
    )
    os.utime(path, (1768478400, 1768478400))
    for name, records in (("context.jsonl", context), ("wire.jsonl", wire)):
        if records is not None:
            write_jsonl(directory / name, records)
            os.utime(directory / name, (1768478400, 1768478400))
    return directory


def wire_event(kind, **payload):
    return {"timestamp": 1768478400.123, "message": {"type": kind, "payload": payload}}


def export(cli):
    result = cli.run(f"kimi://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    return json.loads(next((cli.root / "exports/kimi").glob("*.json")).read_text())


def status(**usage):
    return wire_event("StatusUpdate", token_usage=usage)


def test_status_usage_counts_cache_and_subagents_and_marks_wire_messages(cli):
    directory = create(
        cli,
        wire=[
            wire_event("TurnBegin", user_input=[{"text": "Start"}]),
            wire_event("ContentPart", type="text", text="Answer"),
            status(input_other=20, output=8, input_cache_read=5, input_cache_creation=2),
            status(input_other=1, output=1),
            {"message": {"usage": {"input_tokens": 100, "output_tokens": 100}}},
        ],
    )
    write_jsonl(directory / "subagents/a1/wire.jsonl", [status(input_other=30, output=6, input_cache_read=10)])
    (cli.root / "sources/kimi/config.toml").write_text('default_model = "kimi-k2"\n')
    payload = export(cli)
    assert (payload["stats"]["total_input_tokens"], payload["stats"]["total_output_tokens"]) == (68, 15)
    user, assistant = payload["messages"]
    assert user["tokens"] == {}
    assert assistant["model"] == "kimi-k2"
    assert assistant["tokens"] == {"input": 28, "output": 9, "cache": {"read": 5, "write": 2}}
