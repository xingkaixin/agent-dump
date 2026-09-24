"""Synthetic desktop Provider data shared by CLI parity cases."""

import importlib
import json

from cli_fixture import ROOT, make_cli

NOW = 1768478400000
PROVIDERS = {
    "deepchat": ("DEEPCHAT_USER_DATA_DIR", "app_db/agent.db", "deepchat-contract"),
    "cherry": ("CHERRY_STUDIO_USER_DATA_DIR", "Data/cherrystudio.sqlite", "session-contract"),
    "minimax": ("MINIMAX_DATA_DIR", "v2/sqlite/runtime-state.sqlite", "minimax-contract"),
}


def desktop(tmp_path, monkeypatch, provider):
    cli = make_cli(tmp_path, monkeypatch)
    monkeypatch.syspath_prepend(str(ROOT / "tests"))
    module = importlib.import_module(f"{provider}_fixtures")
    variable, suffix, identity = PROVIDERS[provider]
    root = tmp_path / "sources" / f"{provider} #?库"
    cli.source = getattr(module, f"create_{provider}_db")(root / suffix, NOW)
    cli.environment[variable] = str(root)
    return cli, identity


def exports(cli, provider, identity, lang="en"):
    cli.parity(
        f"{provider}://{identity}",
        "--format",
        "json,md,print",
        "--output",
        "exports",
        "--lang",
        lang,
        formats=("json", "markdown"),
    )
    return json.loads(next((cli.root / "exports" / provider).glob("*.json")).read_text())


def fails(cli, uri, formats="json,md,print"):
    before = cli.fixtures.source_manifest(cli.root)
    for candidate in ("python", "rust"):
        result = cli.run(candidate, uri, "--format", formats, "--output", "exports", "--lang", "en")
        assert result.returncode != 0, result.stdout + result.stderr
        assert not [p for p in (cli.root / "exports").rglob("*") if p.is_file()]
        assert cli.fixtures.source_manifest(cli.root) == before
