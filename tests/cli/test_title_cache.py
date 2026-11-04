"""Title indexes are optional metadata, with warnings scoped to each operation."""

import json

from cli_fixture import IDENTITY, ROOT
from test_claude import create as create_claude, event


def test_unreadable_index_recovers_with_warning(cli):
    source = create_claude(cli, [event("user", "Keep")])
    create_claude(cli, [event("user", "Other", timestamp="2026-01-14T12:00:00+00:00")], identity="other")
    index = source.parent / "sessions-index.json"
    if index.exists():
        index.unlink()
    index.write_bytes(b'{"entries": [')
    catalog = json.loads((ROOT / "resources/locales/en.json").read_text(encoding="utf-8"))
    prefix = catalog["WARN_TITLE_CACHE_FAILED"].format(error="")
    before = cli.fixtures.source_manifest(cli.root)
    for args in [
        ("--list", "-q", "provider:claude", "-d", "36500"),
        (f"claude://{IDENTITY}", "--head"),
        (f"claude://{IDENTITY}", "--format", "json,raw", "--output", "exports"),
    ]:
        result = cli.run(*args, "--lang", "en")
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(result.stderr.splitlines()) == 1
        assert result.stderr.startswith(prefix) and result.stderr[len(prefix) :].strip()
        assert cli.fixtures.source_manifest(cli.root) == before
    assert f"claude://{IDENTITY}" in cli.run("--list", "-q", "provider:claude", "-d", "36500").stdout
    exported = json.loads((cli.root / "exports/claudecode" / f"{IDENTITY}.json").read_text())
    assert exported["title"] == "Keep"
