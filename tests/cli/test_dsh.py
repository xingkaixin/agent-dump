"""DSH session logs through the published CLI surface."""

import base64
import hashlib
import json
import os

from cli_fixture import IDENTITY

STAMP = 1768478400
STAMP_MS = STAMP * 1000


def frame(data):
    """A zstd frame holding `data` in one raw block, as DSH appends per write."""
    header = bytes([0x28, 0xB5, 0x2F, 0xFD, 0xA0]) + len(data).to_bytes(4, "little")
    return header + (1 | len(data) << 3).to_bytes(3, "little") + data


def header(identity=IDENTITY, **fields):
    record = {"type": "session", "version": 0, "id": identity, "cwd": "/workspace/dsh", "createdAt": STAMP_MS}
    return {**record, "delegationDepth": 0, **fields}


def event(kind, seq, data):
    return {"type": kind, "seq": seq, "time": STAMP_MS + seq * 1000, "surfaceOp": "append", "data": data}


def user(seq, *content, identity=None):
    blocks = [{"type": "text", "text": block} if isinstance(block, str) else block for block in content]
    return event("user/message", seq, {"id": identity or f"u{seq}", "source": {"kind": "user"}, "content": blocks})


def create(cli, records, *, name="session.jsonl", project="--workspace-dsh--", identity=IDENTITY, tail=b""):
    path = cli.root / "sources/dsh/sessions" / project / identity / name
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record).encode() + b"\n" for record in records]
    path.write_bytes(b"".join(map(frame, lines)) + tail if name.endswith(".zstd") else b"".join(lines) + tail)
    os.utime(path, (STAMP, STAMP))
    return path


def image(data):
    digest = hashlib.sha256(data).hexdigest()
    attachment = {"attachmentId": f"sha256:{digest}", "mediaType": "image/png", "bytes": len(data)}
    return digest, {"type": "image", "attachment": attachment}


def run_json(cli, *args):
    result = cli.run(*args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def listed(cli):
    return {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:dsh")}


def test_list_head_and_export(cli):
    digest, stored = image(b"test image")
    _, missing = image(b"never stored")
    objects = cli.root / "sources/dsh/attachments/v1/objects" / digest[:2]
    objects.mkdir(parents=True)
    (objects / digest).write_bytes(b"test image")
    origin = {"provider": "deepseek", "model": "deepseek-chat"}
    usage = {"inputTokens": 10, "cacheReadTokens": 2, "cacheWriteTokens": 3, "outputTokens": 8, "reasoningTokens": 2}
    answer = [
        {"type": "reasoning", "text": "Reason"},
        {"type": "text", "text": "Looking"},
        {"type": "tool-call", "id": "read", "name": "Read_File", "arguments": '{"path":"a.rs"}'},
    ]
    result = [
        {"type": "tool-result", "toolCallId": "read", "isError": True, "content": [{"type": "text", "text": "gone"}]}
    ]
    source = create(
        cli,
        [
            header(),
            event("request/context", 0, {"provider": "deepseek", "model": "deepseek-chat"}),
            user(1, "<system-reminder>hidden</system-reminder>\nFix   the bug\nmore", stored, identity="prompt"),
            event(
                "assistant/message",
                2,
                {
                    "turn": 1,
                    "step": 1,
                    "message": {"id": "answer", "source": origin, "content": answer},
                    "usage": usage,
                },
            ),
            event("tool/call", 3, {"callId": "read", "name": "Read_File", "arguments": {"path": "a.rs"}}),
            event(
                "tool/result",
                4,
                {
                    "message": {"source": {"kind": "tool", "callId": "read"}, "content": result},
                    "meta": {"note": "retry"},
                },
            ),
            user(5, missing, identity="photo"),
            {
                "type": "text-chunks",
                "seq0": 6,
                "time0": STAMP_MS + 6000,
                "data": {"turn": 2, "step": 1, "index": 0, "texts": ["Done ", "now"], "dt": [1000]},
            },
            event(
                "assistant/chunk",
                8,
                {"turn": 2, "step": 1, "chunk": {"type": "usage", "usage": {"inputTokens": 4, "outputTokens": 5}}},
            ),
        ],
    )
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli)[IDENTITY]
    assert {key: record[key] for key in ("title", "created_at", "model", "message_count", "working_directory")} == {
        "title": "Fix the bug",
        "created_at": "2026-01-15T12:00:00.000000+00:00",
        "model": "deepseek-chat",
        "message_count": 4,
        "working_directory": "/workspace/dsh",
    }
    head = run_json(cli, f"dsh://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record

    exported = cli.run(f"dsh://{IDENTITY}", "--format", "json,raw", "--output", "exports")
    assert exported.returncode == 0, exported.stderr
    exports = cli.root / "exports/dsh"
    assert (exports / f"{IDENTITY}.raw.jsonl").read_bytes() == source.read_bytes()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before

    assert payload["stats"] == {
        "total_cost": 0,
        "total_input_tokens": 19,
        "total_output_tokens": 13,
        "message_count": 4,
        "total_tokens": 32,
    }
    prompt, reply, photo, streamed = payload["messages"]
    text, attached = prompt["parts"]
    assert text["text"] == "Fix   the bug\nmore"
    assert attached == {
        "type": "image",
        "mime_type": "image/png",
        "data": base64.b64encode(b"test image").decode(),
        "time_created": STAMP_MS + 1000,
    }
    assert (reply["id"], reply["agent"], reply["model"], reply["provider"]) == (
        "answer",
        "dsh",
        "deepseek-chat",
        "deepseek",
    )
    assert reply["tokens"] == {"input": 15, "output": 6, "reasoning": 2, "cache": {"read": 2, "write": 3}}
    reasoning, said, tool = reply["parts"]
    assert (reasoning["type"], reasoning["text"], said["text"]) == ("reasoning", "Reason", "Looking")
    assert (tool["tool"], tool["title"], tool["callID"], tool["time_created"]) == (
        "Read_File",
        "read_file",
        "read",
        STAMP_MS + 3000,
    )
    assert tool["state"] == {
        "status": "error",
        "input": {"path": "a.rs"},
        "output": [{"type": "text", "text": "gone", "time_created": STAMP_MS + 4000}],
        "metadata": {"note": "retry"},
    }
    assert [part["text"] for part in photo["parts"]] == ["Image attachment unavailable"]
    assert (streamed["id"], streamed["model"], streamed["time_created"]) == (
        "dsh-step-2-1",
        "deepseek-chat",
        STAMP_MS + 6000,
    )
    assert [part["text"] for part in streamed["parts"]] == ["Done now"]
    assert (streamed["tokens"]["input"], streamed["tokens"]["output"]) == (4, 5)
