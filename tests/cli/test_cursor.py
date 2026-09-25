import json
import os
import sqlite3
import sys

from cli_fixture import make_cli
from desktop_fixture import NOW, fails
import pytest


def put(cli, key, value):
    with sqlite3.connect(cli.source) as conn:
        conn.execute("INSERT OR REPLACE INTO cursorDiskKV VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))


def cursor(tmp_path, monkeypatch):
    cli = make_cli(tmp_path, monkeypatch)
    home = tmp_path / "sources" / "cursor-home"
    cli.environment.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "AppData/Roaming"))
    base = (
        "Library/Application Support"
        if sys.platform == "darwin"
        else "AppData/Roaming"
        if os.name == "nt"
        else ".config"
    )
    cli.source = home / base / "Cursor/User/globalStorage/state.vscdb"
    cli.source.parent.mkdir(parents=True)
    with sqlite3.connect(cli.source) as conn:
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    put(
        cli,
        "composerData:parent",
        {
            "name": "  Cursor contract  ",
            "createdAt": NOW,
            "updatedAt": NOW + 1000,
            "usageData": {"contextTokensUsed": 90, "contextTokenLimit": 100, "contextUsagePercent": 90},
        },
    )
    put(
        cli,
        "bubbleId:parent:a-user",
        {
            "type": 1,
            "requestId": "request-parent",
            "text": "prompt",
            "modelInfo": {"modelName": "default"},
            "timingInfo": {"clientRpcSendTime": NOW},
        },
    )
    put(
        cli,
        "bubbleId:parent:b-answer",
        {
            "type": 2,
            "text": "answer",
            "tokenCount": {"inputTokens": 10, "outputTokens": 5},
            "timingInfo": {"clientRpcSendTime": NOW + 1000},
        },
    )
    return cli


def export(cli, identity="request-parent", lang="en"):
    cli.parity(
        f"cursor://{identity}", "--format", "json,print", "--output", "exports", "--lang", lang, formats=("json",)
    )
    return json.loads(next((cli.root / "exports/cursor").glob("*.json")).read_text())


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_cursor_list_head_and_export(tmp_path, monkeypatch, lang):
    cli = cursor(tmp_path, monkeypatch)
    cli.parity("--list", "-d", "36500", "-q", "provider:cursor", "--lang", lang)
    cli.parity("cursor://request-parent", "--head", "--lang", lang)
    data = export(cli, lang=lang)
    assert data["messages"][1]["model"] == "default"
    assert data["stats"]["context_tokens_used"] == 90


@pytest.mark.parametrize("formats", ["raw", "md", "json,markdown", "print,raw"])
def test_cursor_rejects_unsupported_format_combinations(tmp_path, monkeypatch, formats):
    fails(cursor(tmp_path, monkeypatch), "cursor://request-parent", formats)


@pytest.mark.parametrize("identity", ["later-request", "id_%_' OR 1=1--", "请求中文", "other:request"])
def test_non_anchor_request_ids_are_literal(tmp_path, monkeypatch, identity):
    cli = cursor(tmp_path, monkeypatch)
    put(cli, "bubbleId:parent:c-later", {"type": 1, "requestId": identity, "text": "later"})
    cli.parity(f"cursor://{identity}", "--head", "--lang", "en")
    data = export(cli, identity)
    assert data["id"] == identity
    assert len(data["messages"]) == 3


@pytest.mark.parametrize(
    "tool",
    [
        {"name": "read", "params": '{"path":"/not-read"}', "result": {"error": "failed"}},
        {"name": "exec", "rawArgs": "partial", "result": "out", "additionalData": {"status": "success"}},
        {"name": "read", "params": None, "status": 2},
    ],
)
@pytest.mark.parametrize("attach", [False, True])
def test_tools_attach_to_explicit_parent_or_stay_separate(tmp_path, monkeypatch, tool, attach):
    cli = cursor(tmp_path, monkeypatch)
    put(
        cli,
        "bubbleId:parent:c-tool",
        {
            "type": 2,
            "parentBubbleId": "b-answer" if attach else "absent",
            "toolFormerData": {"toolCallId": "call", **tool},
        },
    )
    data = export(cli)
    assert len(data["messages"]) == (2 if attach else 3)


@pytest.mark.parametrize("selection", ["accepted", "reject", None])
@pytest.mark.parametrize("body", [None, "planning"])
def test_plan_approval_and_rejected_payload(tmp_path, monkeypatch, selection, body):
    cli = cursor(tmp_path, monkeypatch)
    put(
        cli,
        "bubbleId:parent:c-plan",
        {
            "type": 2,
            "text": body,
            "toolFormerData": {
                "name": "create_plan",
                "params": '{"plan":"  Steps  "}',
                "result": json.dumps({"rejected": {"reason": "不要", "items": [1, 2]}}),
                "additionalData": {"reviewData": {"selectedOption": selection}},
            },
        },
    )
    data = export(cli)
    part = next(p for m in data["messages"] for p in m["parts"] if p["type"] == "plan")
    assert part["input"] == "Steps"


@pytest.mark.parametrize("mode", ["normal", "repeat", "missing", "self", "cycle"])
def test_subagent_expansion_and_cycles(tmp_path, monkeypatch, mode):
    cli = cursor(tmp_path, monkeypatch)
    target = "parent" if mode == "self" else "absent" if mode == "missing" else "child"
    put(
        cli,
        "composerData:child",
        {
            "name": "Child",
            "createdAt": NOW,
            "modelConfig": {"modelName": "child-model"},
            "subagentInfo": {"parentComposerId": "parent", "subagentTypeName": "explore"},
        },
    )
    put(cli, "bubbleId:child:a", {"type": 2, "text": "Child result", "timingInfo": {"clientRpcSendTime": NOW + 2000}})
    task = {
        "type": 2,
        "toolFormerData": {
            "name": "task_v2",
            "params": {"prompt": "  Explore  ", "subagentType": "worker"},
            "toolCallId": "task-call",
            "result": json.dumps({"agentId": target}),
            "additionalData": {"subagentComposerId": target},
        },
    }
    put(cli, "bubbleId:parent:c-task", task)
    if mode == "repeat":
        put(cli, "bubbleId:parent:d-task", task)
    if mode == "cycle":
        put(
            cli,
            "bubbleId:child:b-task",
            {
                "type": 2,
                "toolFormerData": {
                    "name": "agent",
                    "params": {"description": "parent"},
                    "additionalData": {"subagentComposerId": "parent"},
                },
            },
        )
    export(cli)


@pytest.mark.parametrize(
    "bubble",
    [
        {"type": 1, "codeBlocks": [{"content": "first"}, {"content": "second"}], "text": "ignored"},
        {"type": 2, "thinking": {"text": "reason"}},
        {"type": 2, "text": "priority", "codeBlocks": [{"content": "ignored"}]},
        {"type": 2, "finalText": "fallback", "usage": {"input_tokens": "12", "output_tokens": True}},
        {"type": 2, "text": "   ", "contextWindowStatusAtCreation": {"tokensUsed": 7}},
        {"type": 9, "textDescription": "other"},
    ],
)
def test_alternate_text_and_token_shapes(tmp_path, monkeypatch, bubble):
    cli = cursor(tmp_path, monkeypatch)
    put(cli, "bubbleId:parent:c", bubble)
    export(cli)


@pytest.mark.parametrize("raw", [None, "{broken", "[]", b"\xff", b'{"type":2,"text":"blob"}'])
def test_invalid_and_blob_bubbles(tmp_path, monkeypatch, raw):
    cli = cursor(tmp_path, monkeypatch)
    with sqlite3.connect(cli.source) as conn:
        conn.execute("INSERT INTO cursorDiskKV VALUES ('bubbleId:parent:c', ?)", (raw,))
        conn.execute("INSERT INTO cursorDiskKV VALUES ('composerData:broken', NULL)")
    cli.parity("--list", "-d", "36500", "-q", "provider:cursor", "--lang", "en")
    export(cli)


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Shanghai"])
@pytest.mark.parametrize(
    "stamp", ["2026-01-15T12:00:00", "2026-01-15T12:00:00+08:00", 1768478400000, "1768478400", "invalid"]
)
def test_timestamp_fallbacks_and_host_timezone(tmp_path, monkeypatch, timezone, stamp):
    cli = cursor(tmp_path, monkeypatch)
    cli.environment["TZ"] = timezone
    put(cli, "composerData:parent", {"createdAt": stamp, "lastSendTime": NOW})
    put(
        cli,
        "bubbleId:parent:b-answer",
        {
            "type": 2,
            "text": "answer",
            "createdAt": stamp,
            "timingInfo": {"clientRpcSendTime": "invalid", "clientSettleTime": NOW},
        },
    )
    cli.parity("cursor://request-parent", "--head", "--lang", "en")
    export(cli)


@pytest.mark.parametrize("damaged", [False, True])
def test_bounded_metadata_and_corrupt_json_fallback(tmp_path, monkeypatch, damaged):
    cli = cursor(tmp_path, monkeypatch)
    with sqlite3.connect(cli.source) as conn:
        conn.execute("DELETE FROM cursorDiskKV WHERE key >= 'bubbleId:' AND key < 'bubbleId;'")
    for index in range(25):
        put(
            cli,
            f"bubbleId:parent:{index:03d}",
            {"type": 2, **({"requestId": "late", "modelInfo": {"modelName": "late-model"}} if index == 24 else {})},
        )
    if damaged:
        with sqlite3.connect(cli.source) as conn:
            conn.execute("UPDATE cursorDiskKV SET value = 'bad' WHERE key = 'bubbleId:parent:000'")
    cli.parity("--list", "-d", "36500", "-q", "provider:cursor", "--lang", "en")
    cli.parity("cursor://late", "--head", "--lang", "en")
    export(cli, "late" if damaged else "parent")


def test_discovery_across_multiple_metadata_batches(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    with sqlite3.connect(cli.source) as conn:
        for index in range(103):
            identity = f"composer-{index:03d}"
            conn.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (f"composerData:{identity}", json.dumps({"name": identity, "createdAt": NOW})),
            )
            conn.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (
                    f"bubbleId:{identity}:a",
                    json.dumps({"type": 1, "requestId": f"request-{index:03d}", "modelInfo": {"modelName": "batch"}}),
                ),
            )
    cli.parity("--list", "-d", "36500", "-q", "provider:cursor", "--lang", "en")


def test_composer_identifier_with_separator_keeps_metadata_owner(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    put(cli, "composerData:namespace:session", {"name": "Namespaced", "createdAt": NOW})
    put(
        cli,
        "bubbleId:namespace:session:a",
        {"type": 1, "requestId": "namespaced-request", "text": "payload", "modelInfo": {"modelName": "model"}},
    )
    cli.parity("--list", "-d", "36500", "-q", "provider:cursor", "--lang", "en")
    cli.parity("cursor://namespaced-request", "--head", "--lang", "en")
    export(cli, "namespaced-request")
