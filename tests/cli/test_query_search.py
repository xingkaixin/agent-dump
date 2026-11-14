"""Query/Search and maintenance contracts over isolated, synthetic sources."""

from contextlib import closing
import json
import sqlite3
from urllib.parse import quote

from cli_fixture import IDENTITY, header, message
import pytest


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("provider:missing", "unknown agent name: missing"),
        ("limit:0", "limit must be a positive integer"),
        ("role:user unknown:x", "unknown query field: unknown"),
    ],
)
def test_query_diagnostics_never_broaden_scope(cli, query, reason):
    result = cli.run("--list", "-query", query, "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.startswith(f"Diagnostic\nSummary: Invalid query expression.\nDetails:\n  - {reason}\n")


def test_cold_path_search_retains_global_scores_and_evidence(cli):
    cli.write([header(), message("user", "payload 中文 quartz")])
    before = cli.fixtures.source_manifest(cli.root)
    args = ["--search", "payload", "--days", "36500", "--json"]

    scoped = cli.run(*args, "--query", "path:/project")
    full = cli.run(*args)

    assert scoped.returncode == full.returncode == 0, (scoped.stderr, full.stderr)
    selected = json.loads(scoped.stdout)
    all_matches = json.loads(full.stdout)
    assert selected["status"] == all_matches["status"] == "ok"
    assert len(all_matches["data"]) > 1
    assert selected["data"] == [item for item in all_matches["data"] if item["uri"] == f"codex://{IDENTITY}"]
    assert len(selected["data"]) == 1
    assert cli.fixtures.source_manifest(cli.root) == before


def test_database_message_changes_refresh_search_without_session_timestamp_changes(cli):
    database = cli.root / "sources/opencode.db"
    args = ["--query", "provider:opencode", "--days", "36500", "--json"]
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        initial = cli.run("--search", "delta-wal", *args)
        assert initial.returncode == 0, initial.stderr
        assert json.loads(initial.stdout)["data"] == []
        times = writer.execute("SELECT id, time_created, time_updated FROM session_v2 ORDER BY id").fetchall()
        before_database = database.read_bytes()
        writer.execute(
            "UPDATE session_message SET data = ? WHERE id = ?",
            (json.dumps({"text": "delta-wal 新增正文"}), "ses_bench_000000_0"),
        )
        writer.commit()
        assert writer.execute("SELECT id, time_created, time_updated FROM session_v2 ORDER BY id").fetchall() == times
        assert database.read_bytes() == before_database
        durable = {
            path: path.read_bytes()
            for path in database.parent.rglob("*")
            if path.is_file() and not path.name.endswith("-shm")
        }

        for keyword in ["delta-wal", "新增正文"]:
            result = cli.run("--search", keyword, *args)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["status"] == "ok"
            assert [item["uri"] for item in payload["data"]] == ["opencode://ses_bench_000000"]
        assert all(path.read_bytes() == contents for path, contents in durable.items())


def test_index_failure_falls_back_to_logical_transcript(cli):
    cli.write([header(), message("user", "fallback-needle")])
    cache = cli.root / "cache" / "agent-dump"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "search-index.db").write_bytes(b"invalid sqlite database")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("--search", "fallback-needle", "-q", "provider:codex", "-days", "36500", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"codex://{IDENTITY}" in result.stdout
    assert result.stderr.startswith("⚠️  The Codex search index is unusable (DatabaseError: file is not a database")
    assert result.stderr.endswith("falling back to a file scan. Run `agent-dump --reindex` to rebuild it.\n")
    assert cli.fixtures.source_manifest(cli.root) == before


def test_index_location_cannot_write_inside_provider_source(cli):
    cli.environment["XDG_CACHE_HOME"] = str(cli.root / "sources" / "codex")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("--search", "benchmark", "-q", "provider:codex", "-days", "36500", "--lang", "en")
    assert result.returncode == 0
    assert "falling back to a file scan" in result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before
    assert not (cli.root / "sources" / "codex" / "agent-dump").exists()


@pytest.mark.parametrize("keyword", ["timeout auth", "auth missing"])
def test_query_keyword_uses_search_terms(cli, keyword):
    cli.write([header(), message("user", "Auth retry timeout 认证")])
    uris = []
    for args in (
        ["--list", "-q", f"{keyword} provider:codex"],
        [f"agents:///project?q={quote(keyword)}&providers=codex"],
        ["--search", keyword, "-q", "provider:codex"],
    ):
        result = cli.run(*args, "--days", "36500", "--json")
        assert result.returncode == 0, result.stderr
        uris.append([session["uri"] for session in json.loads(result.stdout)["data"]])
    expected = [] if "missing" in keyword else [f"codex://{IDENTITY}"]
    assert uris == [expected] * 3


def test_tool_error_without_output_is_searchable_and_locatable(cli):
    database = cli.root / "sources/opencode.db"
    needle = "tool-error-only-needle"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute(
            "UPDATE session_message SET data = ? WHERE id = ?",
            (
                json.dumps(
                    {
                        "content": [
                            {
                                "type": "tool",
                                "id": "call_err",
                                "name": "read",
                                "state": {
                                    "status": "error",
                                    "input": {"filePath": "/repo/missing.ts"},
                                    "error": needle,
                                },
                            }
                        ]
                    }
                ),
                "ses_bench_000000_1",
            ),
        )
        writer.commit()

    scoped = ["--query", "provider:opencode", "--days", "36500", "--json"]
    listed = cli.run("--list", "-q", f"{needle} provider:opencode", "--days", "36500", "--json")
    searched = cli.run("--search", needle, *scoped)
    located = cli.run("--search", needle, "--locate", *scoped)
    assert listed.returncode == searched.returncode == located.returncode == 0, (
        listed.stderr,
        searched.stderr,
        located.stderr,
    )

    assert [item["uri"] for item in json.loads(listed.stdout)["data"]] == ["opencode://ses_bench_000000"]
    search_hits = json.loads(searched.stdout)["data"]
    assert len(search_hits) == 1
    assert search_hits[0]["uri"] == "opencode://ses_bench_000000"
    assert needle in search_hits[0]["snippet"]
    locate_hits = json.loads(located.stdout)["data"]
    assert len(locate_hits) == 1
    assert locate_hits[0]["locations"][0]["position"] == 2
    assert needle in locate_hits[0]["locations"][0]["snippet"]
