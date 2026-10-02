"""Machine-readable output contracts using isolated provider records."""

import json
from pathlib import Path

from cli_fixture import IDENTITY, CliFixture, header, message, write_jsonl
import pytest
from test_kimi import create as create_kimi, wire_event


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_machine_list_search_stats(cli, lang):
    cli.write([header(), message("user", "unique-machine-needle"), message("assistant", "resolved")])
    common = ("--json", "-d", "36500", "-q", "provider:codex", "--lang", lang)
    before = cli.fixtures.source_manifest(cli.root)
    listed = cli.run("rust", "--list", *common)
    assert listed.returncode == 0, listed.stderr
    document = json.loads(listed.stdout)
    assert document["schema_version"] == 1
    assert document["kind"] == "list"
    assert document["status"] == "ok"
    record = next(item for item in document["data"] if item["id"] == IDENTITY)
    assert record["uri"] == f"codex://{IDENTITY}"
    assert record["working_directory"] == "/project"
    assert record["message_count"] == 2
    assert record["message_count_completeness"] == "exact"
    search = cli.run("rust", "--search", "unique-machine-needle", *common)
    assert search.returncode == 0, search.stderr
    found = json.loads(search.stdout)
    assert found["kind"] == "search"
    assert [item["id"] for item in found["data"]] == [IDENTITY]
    assert "unique-machine-needle" in found["data"][0]["snippet"]
    stats = cli.run("rust", "--stats", *common)
    assert stats.returncode == 0, stats.stderr
    counts = json.loads(stats.stdout)["data"]
    assert counts["total"]["sessions"] == len(document["data"])
    assert counts["total"]["known_messages"] >= 2
    assert cli.fixtures.source_manifest(cli.root) == before


def test_machine_empty_results_and_diagnostics(cli):
    result = cli.run("rust", "--search", "no-such-machine-match", "--json", "--format", "json", "-d", "36500")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"] == []
    assert result.stderr
    invalid = cli.run("rust", "--interactive", "--json")
    assert invalid.returncode == 1
    assert invalid.stdout == ""
    assert invalid.stderr


def test_machine_partial_discovery(cli):
    database = cli.root / "broken.sqlite"
    database.write_text("not sqlite")
    cli.environment["OPENCODE_DB"] = str(database)
    result = cli.run("rust", "--list", "--json", "-d", "36500")
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "partial"
    assert "opencode" in document["failed_providers"]


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_machine_head_reuses_list_facts_and_canonical_uri(cli: CliFixture, lang: str) -> None:
    cli.write([header(), message("user", "body must not enter head output")])
    before = cli.fixtures.source_manifest(cli.root)
    listed = cli.run("rust", "--list", "--json", "-d", "36500", "-q", "provider:codex", "--lang", lang)
    record = next(item for item in json.loads(listed.stdout)["data"] if item["id"] == IDENTITY)
    result = cli.run("rust", f"codex://threads/{IDENTITY}", "--head", "--json", "--lang", lang)
    assert result.returncode == 0 and not result.stderr
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1 and document["kind"] == "head" and document["status"] == "ok"
    assert {key: document["data"][key] for key in record} == record
    assert {"project", "version", "subtargets"} <= document["data"].keys()
    assert document["data"]["message_count"] == 1
    assert "body must not enter head output" not in result.stdout
    assert cli.fixtures.source_manifest(cli.root) == before


def test_machine_head_unknown_facts_are_null(cli: CliFixture) -> None:
    create_kimi(cli, wire=[wire_event("ContentPart", type="text", text="Wire body")], cwd="")
    result = cli.run("rust", f"kimi://{IDENTITY}", "--head", "--json")
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)["data"]
    assert record["message_count"] is None
    assert record["message_count_completeness"] == "unknown"
    assert record["working_directory"] is None and record["model"] is None


def test_machine_head_partial_lookup_keeps_diagnostics_outside_json(cli: CliFixture) -> None:
    write_jsonl(cli.source.parent / f"bad-{IDENTITY}.jsonl", [{"type": "session_meta", "payload": 42}])
    cli.source.rename(cli.source.with_name("fallback.jsonl"))
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--head", "--json")
    assert result.returncode == 0 and result.stderr
    document = json.loads(result.stdout)
    assert document["kind"] == "head" and document["status"] == "partial"
    assert document["data"]["id"] == IDENTITY
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "args",
    [
        ["codex://missing"],
        ["unsupported://session"],
        [f"codex://{IDENTITY}", "--format", "json"],
        [f"codex://{IDENTITY}", "--summary"],
        [f"codex://{IDENTITY}", "--read"],
    ],
)
def test_machine_head_failures_do_not_emit_invalid_json(cli: CliFixture, lang: str, args: list[str]) -> None:
    result = cli.run("rust", *args, "--head", "--json", "--lang", lang)
    assert result.returncode == 1
    assert not result.stdout and result.stderr


def test_machine_provider_capabilities_use_metadata_without_reading_sources(cli: CliFixture) -> None:
    cli.source.write_text("not a valid session")
    Path(cli.environment["OPENCODE_DB"]).write_bytes(b"not a database")
    before = cli.fixtures.source_manifest(cli.root)
    documents = []
    for flag, lang in [("--providers", "en"), ("--capabilities", "zh")]:
        result = cli.run("rust", flag, "--json", "--list", "--lang", lang)
        assert result.returncode == 0 and result.stderr
        document = json.loads(result.stdout)
        assert document["schema_version"] == 1 and document["kind"] == "providers" and document["status"] == "ok"
        records = {item["scheme"]: item for item in document["data"]}
        assert set(records) == {
            "opencode",
            "zcode",
            "codex",
            "kimi",
            "claude",
            "cursor",
            "pi",
            "deepchat",
            "cherry",
            "minimax",
        }
        assert records["claude"]["provider"] == "claudecode"
        assert records["codex"]["uri_prefixes"] == ["threads/"]
        for scheme, record in records.items():
            assert record["display_name"] and record["identifier_label"]
            if scheme == "cursor":
                formats = ["json", "print"]
            elif scheme in {"deepchat", "cherry", "minimax"}:
                formats = ["json", "markdown", "print"]
            else:
                formats = ["json", "markdown", "print", "raw"]
            assert record["formats"] == formats
            for root in record["search_roots"]:
                assert root["label"] and root["path"]
                assert root["exists"] == Path(root["path"]).exists()
        documents.append(document)
    assert documents[0] == documents[1]
    assert cli.fixtures.source_manifest(cli.root) == before
