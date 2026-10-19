"""Title indexes are optional metadata, with warnings scoped to each operation."""

import json

from cli_fixture import IDENTITY, ROOT, header, message, write_jsonl
import pytest
from test_claude import create as create_claude, event


def sessions(cli, provider):
    if provider == "codex":
        cli.write([header(), message("user", "Keep")])
        write_jsonl(
            cli.source.parent / "rollout-other.jsonl",
            [header("other", timestamp="2026-01-14T12:00:00+00:00"), message("user", "Other")],
        )
        return cli.root / "sources/codex/session_index.jsonl"
    source = create_claude(cli, [event("user", "Keep")])
    create_claude(cli, [event("user", "Other", timestamp="2026-01-14T12:00:00+00:00")], identity="other")
    return source.parent / "sessions-index.json"


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("damage", ["directory", "json", "utf8"])
def test_unreadable_index_recovers_with_localized_warning(cli, language, damage):
    index = sessions(cli, "claude")
    if index.exists():
        index.unlink()
    if damage == "directory":
        index.mkdir()
    else:
        index.write_bytes(b'{"entries": [' if damage == "json" else b'{"entries": [\xff]}')
    catalog = json.loads((ROOT / "resources/locales" / f"{language}.json").read_text(encoding="utf-8"))
    prefix = catalog["WARN_TITLE_CACHE_FAILED"].format(error="")
    before = cli.fixtures.source_manifest(cli.root)
    for args in [
        ("--list", "-q", "provider:claude", "-d", "36500"),
        (f"claude://{IDENTITY}", "--head"),
        (f"claude://{IDENTITY}", "--format", "json,raw", "--output", "exports"),
    ]:
        result = cli.run(*args, "--lang", language)
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(result.stderr.splitlines()) == 1
        assert result.stderr.startswith(prefix) and result.stderr[len(prefix) :].strip()
        if damage == "directory":
            assert repr(str(index)) in result.stderr
        assert cli.fixtures.source_manifest(cli.root) == before
    assert f"claude://{IDENTITY}" in cli.run("--list", "-q", "provider:claude", "-d", "36500").stdout
    exported = json.loads((cli.root / "exports/claudecode" / f"{IDENTITY}.json").read_text())
    assert exported["title"] == "Keep"
