from datetime import datetime, timezone
import json
import sys

from deepchat_fixtures import create_deepchat_db
from locale_helpers import expect
import pytest

from agent_dump.cli import main
from agent_dump.i18n import Keys


@pytest.fixture
def deepchat_database(isolated_provider_home, monkeypatch):
    root = isolated_provider_home / "deepchat"
    monkeypatch.setenv("DEEPCHAT_USER_DATA_DIR", str(root))
    return create_deepchat_db(root / "app_db" / "agent.db", int(datetime.now(timezone.utc).timestamp() * 1000))


@pytest.mark.parametrize(
    "args",
    [
        ["--list", "-query", "provider:deepchat role:user prompt"],
        ["--search", "answer", "-query", "provider:deepchat"],
        ["deepchat://deepchat-contract", "--head"],
    ],
)
def test_deepchat_query_search_and_head(deepchat_database, monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["agent-dump", *args])
    assert main() == 0
    assert "deepchat://deepchat-contract" in capsys.readouterr().out


def test_deepchat_print_and_file_exports(deepchat_database, monkeypatch, capsys, tmp_path):
    output = tmp_path / "exports"
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-dump", "deepchat://deepchat-contract", "--format", "print,json,md", "--output", str(output)],
    )
    assert main() == 0
    printed = capsys.readouterr().out
    assert "DeepChat prompt" in printed
    assert "DeepChat answer" in printed
    (json_path,) = output.rglob("*.json")
    (markdown_path,) = output.rglob("*.md")
    assert json.loads(json_path.read_text())["messages"][0]["parts"][0]["text"] == "DeepChat prompt"
    assert "DeepChat answer" in markdown_path.read_text()


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_deepchat_unsupported_formats_and_encryption(deepchat_database, monkeypatch, capsys, lang):
    monkeypatch.setattr(sys, "argv", ["agent-dump", "--lang", lang, "deepchat://deepchat-contract", "--format", "raw"])
    assert main() == 1
    assert expect(Keys.DIAG_URI_CAPABILITY_GAP, agent="DeepChat") in capsys.readouterr().out
    deepchat_database.write_bytes(b"encrypted database" * 100)
    monkeypatch.setattr(sys, "argv", ["agent-dump", "--lang", lang, "deepchat://deepchat-contract"])
    assert main() == 1
    captured = capsys.readouterr()
    assert expect(Keys.DIAG_DEEPCHAT_UNREADABLE) in captured.err + captured.out
