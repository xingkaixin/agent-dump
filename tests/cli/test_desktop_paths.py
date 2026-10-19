import json
import os
import shutil
import sqlite3
import sys

from desktop_fixture import PROVIDERS, desktop
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
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"{provider}://{identity}", "--format", "json", "--output", "exports", "--lang", "en")
    assert cli.fixtures.source_manifest(cli.root) == before
    if mode == "missing":
        assert result.returncode == 1, result.stdout + result.stderr
        assert result.stdout.startswith("Diagnostic\nSummary: No matching session found.\n")
        assert not (root / "missing").exists()
        assert not (cli.root / "exports").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(list((cli.root / "exports" / provider).glob("*.json"))) == 1


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


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
def test_wal_changes_are_visible_without_changing_persistent_data(tmp_path, monkeypatch, provider):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    mutations = {
        "deepchat": "UPDATE deepchat_assistant_blocks SET text_content = ?",
        "cherry": "UPDATE agent_session_message SET data = ? WHERE role = 'assistant'",
        "minimax": "UPDATE local_runtime_message_rows SET data_json = ? WHERE msg_id = 'assistant-1'",
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
            }[provider]
            writer.execute(mutations[provider], (value,))
            writer.commit()
            files = sorted(p for p in cli.source.parent.iterdir() if p.is_file())
            before = {p.name: p.read_bytes() for p in files if not p.name.endswith("-shm")}
            output = cli.root / "exports"
            shutil.rmtree(output, ignore_errors=True)
            result = cli.run(
                "rust", f"{provider}://{identity}", "--format", "json", "--output", "exports", "--lang", "en"
            )
            assert result.returncode == 0, result.stdout + result.stderr
            payload = json.loads(next(output.rglob("*.json")).read_text())
            assert text in json.dumps(payload)
            assert {p.name: p.read_bytes() for p in files if not p.name.endswith("-shm")} == before
            assert sorted(p for p in cli.source.parent.iterdir() if p.is_file()) == files
    finally:
        writer.close()


def head(cli, uri):
    result = cli.run("rust", uri, "--head", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("variable", ["CURSOR_DATA_PATH", "XDG_CONFIG_HOME"])
def test_cursor_user_directory_variables(tmp_path, monkeypatch, variable):
    if variable == "XDG_CONFIG_HOME" and sys.platform != "linux":
        pytest.skip("XDG_CONFIG_HOME locates Cursor only on Linux")
    cli = cursor(tmp_path, monkeypatch)
    root = tmp_path / "custom config"
    user = root / "User" if variable == "CURSOR_DATA_PATH" else root / "Cursor/User"
    # Windows keeps the fixture database open, so copy it and hide the default root instead of moving it.
    shutil.copytree(cli.source.parent, user / "globalStorage")
    other = tmp_path / "other home"
    cli.environment.update(
        HOME=str(other),
        USERPROFILE=str(other),
        APPDATA=str(other / "AppData/Roaming"),
        XDG_CONFIG_HOME=str(other / ".config"),
    )
    cli.environment[variable] = str(user if variable == "CURSOR_DATA_PATH" else root)
    head(cli, "cursor://request-parent")


def test_cherry_codesesh_variable_takes_precedence(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "cherry")
    cli.environment["CHERRYSTUDIO_USER_DATA_DIR"] = cli.environment["CHERRY_STUDIO_USER_DATA_DIR"]
    cli.environment["CHERRY_STUDIO_USER_DATA_DIR"] = str(tmp_path / "missing")
    head(cli, f"cherry://{identity}")


def test_minimax_falls_back_to_legacy_home_directory(tmp_path, monkeypatch):
    cli, identity = desktop(tmp_path, monkeypatch, "minimax")
    home = tmp_path / "sources/home"
    target = home / ".minimax-code/v2/sqlite/runtime-state.sqlite"
    target.parent.mkdir(parents=True)
    shutil.copyfile(cli.source, target)
    (home / ".minimax").mkdir()
    cli.environment.update(HOME=str(home), USERPROFILE=str(home))
    cli.environment.pop("MINIMAX_DATA_DIR")
    cli.environment.pop("MAVIS_DATA_DIR")
    head(cli, f"minimax://{identity}")
