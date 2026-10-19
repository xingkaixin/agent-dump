"""Query/Search and maintenance contracts over isolated, synthetic sources."""

from contextlib import closing
import json
import sqlite3
from urllib.parse import quote

from cli_fixture import IDENTITY, call, header, message
import pytest


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("", "query expression cannot be empty"),
        ("  ", "query expression cannot be empty"),
        ("provider:", "providers cannot be empty"),
        ("provider:missing", "unknown agent name: missing"),
        ("codex,missing:auth", "unknown agent name: missing"),
        ("codex:", "query keyword cannot be empty"),
        ("role:", "roles cannot be empty"),
        ("path:", "query path cannot be empty"),
        ("limit:", "limit cannot be empty"),
        ("limit:0", "limit must be a positive integer"),
        ("limit:-1", "limit must be a positive integer"),
        ("limit:1.5", "limit must be a positive integer"),
        ("limit:9223372036854775808", "limit is too large"),
        ("path:. cwd:.", "path/cwd may only be given once"),
        ("limit:1 limit:2", "limit may only be given once"),
        ("role:user unknown:x", "unknown query field: unknown"),
        ('role:"user', "structured query has invalid quoting or escaping"),
        ("provider:codex trailing\\", "structured query has invalid quoting or escaping"),
    ],
)
def test_query_diagnostics_never_broaden_scope(cli, query, reason):
    result = cli.run("--list", "-query", query, "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.startswith(f"Diagnostic\nSummary: Invalid query expression.\nDetails:\n  - {reason}\n")


@pytest.mark.parametrize(
    ("args", "summary", "reason"),
    [
        (["agents://"], "Invalid agents:// query.", "query path cannot be empty"),
        (["agents://.?limit=0"], "Invalid agents:// query.", "limit must be a positive integer"),
        (["agents://.?q=a&q=b"], "Invalid agents:// query.", "query field may only be given once: q"),
        (["agents://.?unknown=x"], "Invalid agents:// query.", "unknown query field: unknown"),
        (
            ["agents://.?q=auth", "-query", "auth"],
            "Invalid query argument combination.",
            "an agents:// query cannot be combined with -q/--query",
        ),
    ],
)
def test_query_uri_diagnostics(cli, args, summary, reason):
    result = cli.run(*args, "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout.splitlines()[:5] == [
        "Diagnostic",
        f"Summary: {summary}",
        f"Parsed URI: {args[0]}",
        "Details:",
        f"  - {reason}",
    ]


@pytest.mark.parametrize("mode", ["query", "search"])
@pytest.mark.parametrize("keyword", ["payload", "中文", "q"])
def test_empty_path_scope_does_not_create_a_search_index(cli, mode, keyword):
    before = cli.fixtures.source_manifest(cli.root)
    scope = "path:/no-matching-project"
    args = ["--days", "36500", "--json"]
    args += ["--search", keyword, "--query", scope] if mode == "search" else ["--list", "--query", f"{keyword} {scope}"]

    result = cli.run(*args)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["data"] == []
    assert not (cli.root / "cache" / "agent-dump" / "search-index.db").exists()
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("keyword", ["payload", "中文", "q"])
def test_cold_path_search_retains_global_scores_and_evidence(cli, keyword):
    cli.write([header(), message("user", "payload 中文 quartz")])
    before = cli.fixtures.source_manifest(cli.root)
    args = ["--search", keyword, "--days", "36500", "--json"]

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


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_database_message_changes_refresh_search_without_session_timestamp_changes(cli, journal):
    database = cli.root / "sources/opencode.db"
    args = ["--query", "provider:opencode", "--days", "36500", "--json"]
    with closing(sqlite3.connect(database)) as writer:
        writer.execute(f"PRAGMA journal_mode={journal}")
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
        if journal == "WAL":
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


@pytest.mark.parametrize(
    ("kind", "cause"), [("database", "DatabaseError: file is not a database"), ("directory", "FileExistsError: ")]
)
def test_index_failures_fall_back_to_logical_transcript(cli, kind, cause):
    cli.write([header(), message("user", "fallback-needle")])
    cache = cli.root / "cache" / "agent-dump"
    cache.mkdir(parents=True, exist_ok=True)
    if kind == "database":
        (cache / "search-index.db").write_bytes(b"invalid sqlite database")
    else:
        cache.rmdir()
        cache.write_text("a file instead of the cache directory")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("--search", "fallback-needle", "-q", "provider:codex", "-days", "36500", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"codex://{IDENTITY}" in result.stdout
    assert result.stderr.startswith(f"⚠️  The Codex search index is unusable ({cause}")
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


@pytest.mark.parametrize("keyword", ["timeout auth", "Auth   认证", "auth missing"])
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


def test_role_filter_keeps_tool_state_in_search_corpus(cli):
    cli.write([header(), call(arguments={"cmd": "quartz-marker"})])
    for args in (
        ["--list", "-q", "quartz-marker role:assistant provider:codex"],
        ["--search", "quartz-marker", "-q", "role:assistant provider:codex"],
    ):
        result = cli.run(*args, "--days", "36500", "--json")
        assert result.returncode == 0, result.stderr
        assert [session["uri"] for session in json.loads(result.stdout)["data"]] == [f"codex://{IDENTITY}"]
