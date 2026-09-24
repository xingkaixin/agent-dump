"""Query/Search and maintenance contracts over isolated, synthetic sources."""

from contextlib import closing
import shutil
import sqlite3

from cli_fixture import call, header, message, output, reasoning
import pytest


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("mode", ["query", "search"])
@pytest.mark.parametrize(
    "keyword",
    [
        "authentication",
        "Auth Timeout",
        "timeout auth",
        "AUTH",
        "认证",
        "认证 超时",
        "超",
        "a+b",
        '"quoted"',
        "AND NEAR *",
        "i",
        "İ",
        "ı",
        "ſ",
        "K",
        "straße",
        "STRASSE",
        "tool-only",
        "reason-only",
        "private-field",
        "missing",
        "😺",
        "auth\x1ctimeout",
    ],
)
def test_literal_matching_rank_and_snippets(cli, lang, mode, keyword):
    cli.write(
        [
            header(),
            message("user", "Auth incident"),
            message(
                "assistant", 'Authentication timeout\n认证超时 a+b literal AND NEAR * and "quoted" 😺 İ ı ſ K Straße'
            ),
            reasoning("reason-only"),
            call(arguments={"query": "tool-only", "认证": "逻辑值"}),
            output("finished"),
        ]
    )
    args = ["--lang", lang, "-days", "36500"]
    if mode == "query":
        args += ["--list", "-query", f"codex:{keyword}"]
    else:
        args += ["--search", keyword, "-query", "provider:codex"]
    cli.parity(*args)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "query",
    [
        "provider:codex",
        "provider:CODEX role:USER",
        "role:user auth provider:codex",
        "role:assistant auth provider:codex",
        "role:system provider:codex",
        "role:user,assistant limit:1",
        'auth provider:codex path:"/project"',
        "provider:codex path:/project/child",
        "provider:codex cwd:/other",
        "provider:codex role:assistant reason-only",
        "provider:codex role:tool tool-only",
        "provider:codex limit:2",
    ],
)
def test_structured_query_scope_roles_and_global_limit(cli, lang, query):
    cli.write(
        [
            header(),
            message("user", "auth user"),
            message("assistant", "assistant-only"),
            reasoning("reason-only"),
            call(arguments="tool-only"),
        ]
    )
    cli.parity("--list", "-q", query, "-d", "36500", "--lang", lang)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "query",
    [
        "",
        "provider:",
        "provider:missing",
        "codex,missing:auth",
        "codex:",
        "role:",
        "path:",
        "limit:",
        "limit:0",
        "limit:-1",
        "limit:1.5",
        "limit:9223372036854775808",
        "path:. cwd:.",
        "limit:1 limit:2",
        "role:user unknown:x",
        'role:"user',
        "provider:codex trailing\\",
    ],
)
def test_query_diagnostics(cli, lang, query):
    cli.parity("--list", "-query", query, "--lang", lang, exit_code=1)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "uri",
    [
        "agents:///project?providers=codex&q=Auth",
        "agents:///project?roles=user&limit=1",
        "agents:///project/child?providers=codex",
        "agents:///other?providers=codex",
        "agents:///project?q=auth+timeout&providers=codex",
        "agents:///project?q=%E8%AE%A4%E8%AF%81",
    ],
)
def test_query_uri(cli, lang, uri):
    cli.write([header(), message("user", "Auth timeout 认证")])
    cli.parity(uri, "-days", "36500", "--lang", lang)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "args",
    [
        ["agents://"],
        ["agents://.?limit=0"],
        ["agents://.?q=a&q=b"],
        ["agents://.?unknown=x"],
        ["agents://.?q=auth", "-query", "auth"],
    ],
)
def test_query_uri_diagnostics(cli, lang, args):
    cli.parity(*args, "--lang", lang, exit_code=1)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "args",
    [
        ["--stats"],
        ["--stats", "-q", "provider:codex"],
        ["--stats", "-q", "missing"],
        ["--stats", "-q", "role:user limit:2"],
        ["--providers"],
        ["--reindex"],
    ],
)
def test_maintenance(cli, lang, args):
    cli.parity(*args, "-days", "36500", "--lang", lang)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "keyword", ["authentication", "needle", "benchmark", "认证", "auth timeout", "x", "never-matches"]
)
@pytest.mark.parametrize("limit", [None, 1, 4])
def test_cross_provider_ranking_uses_global_index_snapshot(cli, lang, keyword, limit):
    args = ["--search", keyword, "-days", "36500", "--lang", lang]
    if limit:
        args += ["-q", f"limit:{limit}"]
    cli.parity(*args)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("kind", ["database", "directory"])
def test_index_failures_fall_back_to_logical_transcript(cli, lang, kind):
    cache = cli.root / "cache" / "agent-dump"
    cache.mkdir(parents=True, exist_ok=True)
    if kind == "database":
        (cache / "search-index.db").write_bytes(b"invalid sqlite database")
    else:
        cache.rmdir()
        cache.write_text("a file instead of the cache directory")
    cli.parity("--search", "auth", "-q", "provider:codex", "-days", "36500", "--lang", lang)


def test_rust_reuses_python_index_signatures_and_private_permissions(cli):
    cli.write([header(), message("user", "Unicode 😺 认证")])
    args = ["--search", "认证", "-q", "provider:codex", "-days", "36500", "--lang", "en"]
    reference = cli.run("python", *args)
    path = cli.root / "cache" / "agent-dump" / "search-index.db"
    with closing(sqlite3.connect(path)) as connection:
        before = list(
            connection.execute("SELECT session_id, updated_signature, indexed_at FROM index_state ORDER BY session_id")
        )
    candidate = cli.run("rust", *args)
    assert candidate.returncode == reference.returncode == 0
    assert candidate.stdout == reference.stdout
    with closing(sqlite3.connect(path)) as connection:
        assert (
            list(
                connection.execute(
                    "SELECT session_id, updated_signature, indexed_at FROM index_state ORDER BY session_id"
                )
            )
            == before
        )


def test_index_location_cannot_write_inside_provider_source(cli):
    cli.environment["XDG_CACHE_HOME"] = str(cli.root / "sources" / "codex")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", "--search", "benchmark", "-q", "provider:codex", "-days", "36500", "--lang", "en")
    assert result.returncode == 0
    assert "falling back to a file scan" in result.stderr
    assert cli.fixtures.source_manifest(cli.root) == before
    assert not (cli.root / "sources" / "codex" / "agent-dump").exists()


def test_index_reuses_unchanged_content_and_refreshes_changed_text(cli):
    original = cli.source.read_bytes()
    before = cli.fixtures.source_manifest(cli.root)
    outputs = []
    for candidate in ["python", "rust"]:
        shutil.rmtree(cli.root / "cache", ignore_errors=True)
        cli.write([header(), message("user", "first needle")])
        args = ["--search", "needle", "-days", "36500", "-query", "provider:codex", "--lang", "en"]
        cold = cli.run(candidate, *args)
        warm = cli.run(candidate, *args)
        assert cold.returncode == warm.returncode == 0
        assert cold.stdout == warm.stdout
        assert warm.stderr == ""
        cli.write([header(), message("user", "second replacement")])
        changed = cli.run(candidate, *args)
        assert changed.returncode == 0
        assert "first needle" not in changed.stdout
        outputs.append((cold.stdout, warm.stdout, changed.stdout))
    assert outputs[0] == outputs[1]
    cli.source.write_bytes(original)
    assert cli.fixtures.source_manifest(cli.root) == before
