import json
import os
import sqlite3
import sys

from cli_fixture import make_cli
from desktop_fixture import NOW
import pytest


def put(cli, key, value):
    with sqlite3.connect(cli.source) as conn:
        conn.execute("INSERT OR REPLACE INTO cursorDiskKV VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))


def cursor(tmp_path, monkeypatch):
    cli = make_cli(tmp_path, monkeypatch)
    home = tmp_path / "sources" / "cursor-home"
    cli.environment.update(
        HOME=str(home),
        USERPROFILE=str(home),
        APPDATA=str(home / "AppData/Roaming"),
        XDG_CONFIG_HOME=str(home / ".config"),
    )
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
            "composerId": "parent",
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


@pytest.mark.parametrize(
    ("formats", "rejected"),
    [("raw", ["raw"]), ("md", ["markdown"]), ("json,markdown", ["markdown"]), ("raw,md,json,raw", ["raw", "markdown"])],
)
def test_cursor_rejects_unsupported_format_combinations(tmp_path, monkeypatch, formats, rejected):
    cli = cursor(tmp_path, monkeypatch)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "cursor://request-parent", "--format", formats, "--output", "exports", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.splitlines()[:4] == [
        "Diagnostic",
        "Summary: The current request uses an export capability Cursor does not support.",
        f"Capability gap: Cursor supports only json, print; requested {','.join(rejected)}",
        "Next steps:",
    ]
    assert f"  - Remove {', '.join(f'`{item}`' for item in rejected)} and use a supported format." in result.stdout
    assert not (cli.root / "exports").exists()
    assert cli.fixtures.source_manifest(cli.root) == before
