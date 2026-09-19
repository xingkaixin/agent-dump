from datetime import datetime, timezone
import json
import sys

from locale_helpers import expect
from minimax_fixtures import create_minimax_db
import pytest

from agent_dump.cli import main
from agent_dump.i18n import Keys


@pytest.fixture
def minimax_database(isolated_provider_home, monkeypatch):
    root = isolated_provider_home / "minimax"
    monkeypatch.setenv("MINIMAX_DATA_DIR", str(root))
    return create_minimax_db(
        root / "v2" / "sqlite" / "runtime-state.sqlite", int(datetime.now(timezone.utc).timestamp() * 1000)
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--list", "-query", "provider:minimax role:user prompt"],
        ["--list", "-query", "provider:minimax path:/workspace/minimax-contract"],
        ["--search", "工具完成 ready", "-query", "provider:minimax"],
        ["minimax://minimax-contract", "--head"],
    ],
)
def test_query_search_and_head(minimax_database, monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["agent-dump", *args])
    assert main() == 0
    assert "minimax://minimax-contract" in capsys.readouterr().out


def test_print_and_file_exports(minimax_database, monkeypatch, capsys, tmp_path):
    output = tmp_path / "exports"
    monkeypatch.setattr(
        sys, "argv", ["agent-dump", "minimax://minimax-contract", "--format", "print,json,md", "--output", str(output)]
    )
    assert main() == 0
    printed = capsys.readouterr().out
    assert "MiniMax prompt" in printed
    assert "MiniMax answer" in printed
    (json_path,) = output.rglob("*.json")
    (markdown_path,) = output.rglob("*.md")
    assert json.loads(json_path.read_text())["messages"][0]["parts"][0]["text"] == "MiniMax prompt"
    assert "MiniMax answer" in markdown_path.read_text()


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_raw_rejected_with_localized_diagnostic(minimax_database, monkeypatch, capsys, lang):
    monkeypatch.setattr(sys, "argv", ["agent-dump", "--lang", lang, "minimax://minimax-contract", "--format", "raw"])
    assert main() == 1
    assert expect(Keys.DIAG_URI_CAPABILITY_GAP, agent="MiniMax Code") in capsys.readouterr().out
