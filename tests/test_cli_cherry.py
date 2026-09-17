from datetime import datetime, timezone
import json
import sqlite3
import sys

from cherry_fixtures import create_cherry_db
from locale_helpers import expect
import pytest

from agent_dump.cli import main
from agent_dump.i18n import Keys


@pytest.fixture(params=["before-soft-delete", "current"])
def cherry_database(isolated_provider_home, monkeypatch, request):
    root = isolated_provider_home / "cherry"
    monkeypatch.setenv("CHERRY_STUDIO_USER_DATA_DIR", str(root))
    database = create_cherry_db(
        root / "Data" / "cherrystudio.sqlite", int(datetime.now(timezone.utc).timestamp() * 1000)
    )
    if request.param == "before-soft-delete":
        with sqlite3.connect(database) as conn:
            conn.execute("ALTER TABLE agent_session DROP COLUMN deleted_at")
    return database


@pytest.mark.parametrize(
    "args",
    [
        ["--list", "-query", "provider:cherry role:user prompt"],
        ["--search", "answer", "-query", "provider:cherry"],
        ["cherry://session-contract", "--head"],
    ],
)
def test_cherry_query_search_and_head(cherry_database, monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["agent-dump", *args])
    assert main() == 0
    assert "cherry://session-contract" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["topic", "session"])
def test_cherry_print_and_file_exports(cherry_database, monkeypatch, capsys, tmp_path, kind):
    output = tmp_path / "exports"
    monkeypatch.setattr(
        sys, "argv", ["agent-dump", f"cherry://{kind}-contract", "--format", "print,json,md", "--output", str(output)]
    )
    assert main() == 0
    printed = capsys.readouterr().out
    assert "Cherry prompt" in printed
    assert "Cherry answer" in printed
    assert "Unselected reply" not in printed
    (json_path,) = output.rglob("*.json")
    (markdown_path,) = output.rglob("*.md")
    assert json.loads(json_path.read_text())["stats"]["message_count"] == 2
    assert "Cherry answer" in markdown_path.read_text()


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_cherry_raw_rejected_with_localized_diagnostic(cherry_database, monkeypatch, capsys, lang):
    monkeypatch.setattr(sys, "argv", ["agent-dump", "--lang", lang, "cherry://topic-contract", "--format", "raw"])
    assert main() == 1
    assert expect(Keys.DIAG_URI_CAPABILITY_GAP, agent="Cherry Studio") in capsys.readouterr().out
