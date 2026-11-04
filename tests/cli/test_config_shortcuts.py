"""Configuration and shortcut CLI contracts, without touching the user's home."""

import os
from pathlib import Path


def config_path(cli):
    base = Path(cli.environment["APPDATA"]) if os.name == "nt" else Path(cli.environment["HOME"]) / ".config"
    path = base / "agent-dump" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_view_masks_api_key(cli):
    key = "secret-key-value"
    path = config_path(cli)
    source = f'[ai]\nprovider="openai"\nbase_url="https://example.invalid/v1"\nmodel="example"\napi_key="{key}"\n'
    path.write_text(source, encoding="utf-8")
    result = cli.run("--config", "view", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "  api_key: sec**********lue\n" in result.stdout
    assert key not in result.stdout + result.stderr
    assert path.read_text(encoding="utf-8") == source
