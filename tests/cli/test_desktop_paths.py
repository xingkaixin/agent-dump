import os
import shutil
import sys

from desktop_fixture import PROVIDERS, desktop
import pytest


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
def test_sessions_export_from_default_paths(tmp_path, monkeypatch, provider):
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
    cli.environment.pop(variable)
    cli.environment.pop("MAVIS_DATA_DIR", None)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(f"{provider}://{identity}", "--format", "json", "--output", "exports", "--lang", "en")
    assert cli.fixtures.source_manifest(cli.root) == before
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list((cli.root / "exports" / provider).glob("*.json"))) == 1
