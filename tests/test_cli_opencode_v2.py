from datetime import datetime, timezone
import json
import sqlite3
import sys

from opencode_fixtures import create_opencode_v2_db, insert_message
import pytest

from agent_dump.cli import main


@pytest.fixture
def opencode_database(isolated_provider_home, monkeypatch):
    path = create_opencode_v2_db(
        isolated_provider_home / "opencode.db", int(datetime.now(timezone.utc).timestamp() * 1000)
    )
    monkeypatch.setenv("OPENCODE_DB", str(path))
    return path


@pytest.mark.parametrize(
    "args",
    [
        ["--list", "-query", "provider:opencode role:user prompt"],
        ["--list", "-query", "provider:opencode path:/workspace/opencode-v2"],
        ["--search", "工具结果 ready", "-query", "provider:opencode"],
        ["opencode://ses_v2", "--head"],
    ],
)
def test_query_search_and_head(opencode_database, monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["agent-dump", *args])
    assert main() == 0
    assert "opencode://ses_v2" in capsys.readouterr().out


def test_print_json_markdown_and_raw(opencode_database, monkeypatch, capsys, tmp_path):
    output = tmp_path / "exports"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-dump",
            "opencode://ses_v2",
            "--format",
            "print,json,md,raw",
            "--output",
            str(output),
        ],
    )
    assert main() == 0
    printed = capsys.readouterr().out
    assert "OpenCode V2 prompt" in printed
    assert "OpenCode V2 answer" in printed
    (raw_path,) = output.rglob("*.raw.json")
    (json_path,) = [path for path in output.rglob("*.json") if path != raw_path]
    (markdown_path,) = output.rglob("*.md")
    raw = json.loads(raw_path.read_text())
    exported = json.loads(json_path.read_text())
    assert raw["messages"] == exported["messages"]
    assert raw["stats"]["message_count"] == 2
    markdown = markdown_path.read_text()
    assert "OpenCode V2 answer" in markdown
    assert raw["messages"][1]["parts"][2]["state"]["output"][0]["text"] == "工具结果 ready"


def test_collect_handoff_uses_v2_session(opencode_database, monkeypatch, capsys, tmp_path):
    with sqlite3.connect(opencode_database) as conn:
        insert_message(conn, "synthetic", {"text": "Synthetic continuation"}, seq=3)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-dump",
            "--collect",
            "--emit-prompt",
            "-query",
            "provider:opencode",
            "--save",
            str(tmp_path / "report.md"),
        ],
    )
    assert main() == 0
    assert "opencode://ses_v2" in capsys.readouterr().out


def test_corrupt_v2_uri_reports_failure(opencode_database, monkeypatch, capsys):
    with sqlite3.connect(opencode_database) as conn:
        conn.execute("UPDATE session_message SET data = '[' WHERE id = 'msg_1'")
    monkeypatch.setattr(sys, "argv", ["agent-dump", "opencode://ses_v2"])
    assert main() == 1
    output = capsys.readouterr()
    assert "msg_1" in output.out + output.err
