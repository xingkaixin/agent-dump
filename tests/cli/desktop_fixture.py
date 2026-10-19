"""Synthetic desktop Provider data shared by CLI contract tests."""

import importlib
import os

from cli_fixture import ROOT, make_cli

NOW = 1768478400000
PROVIDERS = {
    "deepchat": ("DEEPCHAT_USER_DATA_DIR", "app_db/agent.db", "deepchat-contract"),
    "cherry": ("CHERRY_STUDIO_USER_DATA_DIR", "Data/cherrystudio.sqlite", "session-contract"),
    "minimax": ("MINIMAX_DATA_DIR", "v2/sqlite/runtime-state.sqlite", "minimax-contract"),
}


def desktop(tmp_path, monkeypatch, provider):
    cli = make_cli(tmp_path, monkeypatch)
    monkeypatch.syspath_prepend(str(ROOT / "tests" / "cli"))
    module = importlib.import_module(f"{provider}_fixtures")
    variable, suffix, identity = PROVIDERS[provider]
    root = tmp_path / "sources" / (f"{provider} #库" if os.name == "nt" else f"{provider} #?库")
    cli.source = getattr(module, f"create_{provider}_db")(root / suffix, NOW)
    cli.environment[variable] = str(root)
    return cli, identity
