"""Title indexes are optional metadata, with warnings scoped to each operation."""

import json
import os
import shutil

from cli_fixture import IDENTITY, ROOT, header, message, write_jsonl
import pytest
from test_claude import create as create_claude, event


@pytest.fixture(params=["en", "zh"])
def language(request):
    return request.param


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


@pytest.mark.parametrize("document", [[], {"entries": None}, {"entries": {}}])
def test_claude_invalid_index_schema_warns_once_and_preserves_sessions(cli, language, document):
    index = sessions(cli, "claude")
    index.write_text(json.dumps(document))
    for args, formats in [
        (("--list", "-q", "provider:claude", "-d", "36500"), ()),
        ((f"claude://{IDENTITY}", "--head"), ()),
        ((f"claude://{IDENTITY}", "--format", "json,raw", "--output", "exports"), ("json", "raw")),
    ]:
        cli.parity(*args, "--lang", language, formats=formats)
        assert len(cli.run("rust", *args, "--lang", language).stderr.splitlines()) == 1


def test_claude_bad_index_entries_keep_valid_titles_and_aggregate_warning(cli, language):
    index = sessions(cli, "claude")
    index.write_text(
        json.dumps(
            {
                "entries": [
                    None,
                    [],
                    "bad",
                    {},
                    {"sessionId": 3},
                    {"sessionId": ""},
                    {"sessionId": "  "},
                    {"sessionId": IDENTITY, "summary": "Replaced"},
                    {"sessionId": "other", "summary": {"not": "a title"}},
                    {"sessionId": IDENTITY, "summary": "Indexed\n title"},
                ]
            }
        )
    )
    cli.parity("--list", "-q", "provider:claude", "-d", "36500", "--lang", language)
    cli.parity(f"claude://{IDENTITY}", "--head", "--lang", language)
    result = cli.run("rust", f"claude://{IDENTITY}", "--head", "--lang", language)
    assert "Indexed title" in result.stdout
    assert len(result.stderr.splitlines()) == 1 and str(index) in result.stderr
    cli.parity(
        f"claude://{IDENTITY}",
        "--format",
        "json,md,raw,print",
        "--output",
        "exports",
        "--lang",
        language,
        formats=("json", "markdown", "raw"),
    )


@pytest.mark.parametrize("document", [{}, {"entries": []}])
def test_claude_empty_index_has_no_warning(cli, language, document):
    index = sessions(cli, "claude")
    index.write_text(json.dumps(document))
    cli.parity("--list", "-q", "provider:claude", "-d", "36500", "--lang", language)
    assert cli.run("rust", "--list", "-q", "provider:claude", "-d", "36500", "--lang", language).stderr == ""


@pytest.mark.parametrize(
    "provider,damage", [("codex", "directory"), ("claude", "directory"), ("claude", "json"), ("claude", "utf8")]
)
def test_unreadable_index_recovers_with_localized_warning(cli, language, monkeypatch, provider, damage):
    index = sessions(cli, provider)
    if index.exists():
        index.unlink()
    if damage == "directory":
        index.mkdir()
    else:
        index.write_bytes(b'{"entries": [' if damage == "json" else b'{"entries": [\xff]}')
    before = cli.fixtures.source_manifest(cli.root)
    for args in [
        ("--list", "-q", f"provider:{provider}", "-d", "36500"),
        (f"{provider}://{IDENTITY}", "--head"),
        (f"{provider}://{IDENTITY}", "--format", "json,raw", "--output", "exports"),
    ]:
        results = []
        for candidate in ("python", "rust"):
            exports = cli.root / "exports"
            shutil.rmtree(exports, ignore_errors=True)
            result = cli.run(candidate, *args, "--lang", language)
            assert result.returncode == 0, result.stdout + result.stderr
            assert len(result.stderr.splitlines()) == 1
            catalog = json.loads((ROOT / "resources/locales" / f"{language}.json").read_text(encoding="utf-8"))
            prefix = catalog["WARN_TITLE_CACHE_FAILED"].format(error="")
            assert result.stderr.startswith(prefix) and result.stderr[len(prefix) :].strip()
            results.append(
                (
                    result.stdout,
                    {
                        str(path.relative_to(exports)): json.loads(path.read_text())
                        if path.suffix == ".json"
                        else path.read_bytes()
                        for path in exports.rglob("*")
                        if path.is_file()
                    },
                )
            )
            assert cli.fixtures.source_manifest(cli.root) == before
        assert results[0] == results[1]


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("state", ["empty", "expired", "invalid-header"])
def test_index_is_not_read_without_relevant_session_metadata(cli, language, provider, state):
    index = sessions(cli, provider)
    if index.exists():
        index.unlink()
    index.mkdir()
    root = cli.root / "sources" / provider / ("sessions" if provider == "codex" else "projects")
    for path in root.rglob("*.jsonl"):
        if state == "empty":
            path.unlink()
        elif state == "expired":
            os.utime(path, (0, 0))
        else:
            path.write_bytes(b"[]\n")
    days = "1" if state == "expired" else "36500"
    args = ("--list", "-q", f"provider:{provider}", "-d", days, "--lang", language)
    cli.parity(*args)
    assert cli.run("rust", *args).stderr == ""


@pytest.mark.parametrize(
    "summary,failed",
    [
        (1, True),
        (1.5, True),
        (True, True),
        ([1], True),
        ({"text": "bad"}, True),
        (None, False),
        (0, False),
        (False, False),
        ([], False),
        ({}, False),
    ],
)
def test_claude_summary_type_preserves_session_failure_or_title_fallback(cli, language, summary, failed):
    index = sessions(cli, "claude")
    index.write_text(json.dumps({"entries": [{"sessionId": IDENTITY, "summary": summary}]}))
    cli.parity("--list", "-q", "provider:claude", "-d", "36500", "--lang", language)
    cli.parity(f"claude://{IDENTITY}", "--head", "--lang", language, exit_code=1 if failed else 0)
