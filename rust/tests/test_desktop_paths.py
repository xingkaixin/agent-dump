import json
import os
import shutil
import sqlite3
import sys

from desktop_fixture import PROVIDERS, desktop, exports, fails
import pytest
from test_cursor import cursor


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
@pytest.mark.parametrize("mode", ["default", "relative", "missing"])
def test_paths_and_explicit_missing_source(tmp_path, monkeypatch, provider, mode):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    variable, suffix, _ = PROVIDERS[provider]
    home = tmp_path / "sources/home"
    home.mkdir()
    cli.environment.update(
        HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "roaming"), XDG_CONFIG_HOME=str(home / "config")
    )
    if provider == "minimax":
        root = home / ".minimax"
    else:
        base = (
            home / "Library/Application Support"
            if sys.platform == "darwin"
            else home / "roaming"
            if os.name == "nt"
            else home / "config"
        )
        root = base / ("DeepChat" if provider == "deepchat" else "CherryStudio")
    database = root / suffix
    database.parent.mkdir(parents=True)
    shutil.copyfile(cli.source, database)
    if mode == "default":
        cli.environment.pop(variable)
        cli.environment.pop("MAVIS_DATA_DIR", None)
    elif mode == "relative":
        cli.environment[variable] = str(root.relative_to(cli.root))
    else:
        cli.environment[variable] = str(root / "missing")
        fails(cli, f"{provider}://{identity}")
        assert not (root / "missing").exists()
        return
    exports(cli, provider, identity)


@pytest.mark.parametrize(
    "primary,legacy,root_name", [("  ", " ~/old ", "old"), (" ~/selected ", "~/old", "selected"), ("~", None, "")]
)
def test_minimax_override_priority_and_home_expansion(tmp_path, monkeypatch, primary, legacy, root_name):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    home = tmp_path / "sources/home"
    cli.environment.update(HOME=str(home), USERPROFILE=str(home), MINIMAX_DATA_DIR=primary)
    if legacy is not None:
        cli.environment["MAVIS_DATA_DIR"] = legacy
    root = home / root_name
    target = root / "v2/sqlite/runtime-state.sqlite"
    target.parent.mkdir(parents=True)
    shutil.copyfile(cli.source, target)
    exports(cli, "minimax", identity)


def test_cherry_boot_config_relocation(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "cherry")
    root = cli.source.parent.parent
    home = tmp_path / "sources/home"
    boot = home / ".cherrystudio/boot-config.json"
    boot.parent.mkdir(parents=True)
    boot.write_text(
        json.dumps(
            {
                "app.user_data_path": {
                    "relative": "ignored",
                    "missing": str(root / "absent"),
                    "first": str(root),
                    "duplicate": str(root),
                }
            }
        )
    )
    cli.environment.update(HOME=str(home), USERPROFILE=str(home))
    cli.environment.pop("CHERRY_STUDIO_USER_DATA_DIR")
    exports(cli, "cherry", identity)


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax", "cursor"])
def test_provider_source_directory_cannot_be_export_destination(tmp_path, monkeypatch, provider):
    cli, identity = (
        (cursor(tmp_path, monkeypatch), "request-parent")
        if provider == "cursor"
        else desktop(tmp_path, monkeypatch, provider)
    )
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(
        "rust", f"{provider}://{identity}", "--format", "json", "--output", str(cli.source.parent), "--lang", "en"
    )
    assert result.returncode != 0
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax", "cursor"])
def test_wal_changes_are_visible_without_changing_persistent_data(tmp_path, monkeypatch, provider):
    cli, identity = (
        (cursor(tmp_path, monkeypatch), "request-parent")
        if provider == "cursor"
        else desktop(tmp_path, monkeypatch, provider)
    )
    mutations = {
        "deepchat": "UPDATE deepchat_assistant_blocks SET text_content = ?",
        "cherry": "UPDATE agent_session_message SET data = ? WHERE role = 'assistant'",
        "minimax": "UPDATE local_runtime_message_rows SET data_json = ? WHERE msg_id = 'assistant-1'",
        "cursor": "UPDATE cursorDiskKV SET value = ? WHERE key = 'bubbleId:parent:b-answer'",
    }
    writer = sqlite3.connect(cli.source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        for text in ("first committed body", "second committed body"):
            value = {
                "deepchat": text,
                "cherry": json.dumps({"parts": [{"type": "text", "text": text}]}),
                "minimax": json.dumps({"msg_id": "assistant-1", "role": "assistant", "msg_content": text}),
                "cursor": json.dumps({"type": 2, "text": text}),
            }[provider]
            writer.execute(mutations[provider], (value,))
            writer.commit()
            files = sorted(p for p in cli.source.parent.iterdir() if p.is_file())
            before = {p.name: p.read_bytes() for p in files if not p.name.endswith("-shm")}
            payloads = []
            for candidate in ("python", "rust"):
                output = cli.root / "exports"
                shutil.rmtree(output, ignore_errors=True)
                result = cli.run(
                    candidate, f"{provider}://{identity}", "--format", "json", "--output", "exports", "--lang", "en"
                )
                assert result.returncode == 0, result.stdout + result.stderr
                payload = json.loads(next(output.rglob("*.json")).read_text())
                assert text in json.dumps(payload)
                payloads.append(payload)
                assert {p.name: p.read_bytes() for p in files if not p.name.endswith("-shm")} == before
                assert sorted(p for p in cli.source.parent.iterdir() if p.is_file()) == files
            assert payloads[0] == payloads[1]
    finally:
        writer.close()
