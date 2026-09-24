"""Differential CLI contracts against the unchanged Python reference, using only synthetic sources."""

import json
import os
import shutil

from cli_fixture import IDENTITY, STAMP, header, message
import pytest


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("summary", [True, False])
def test_list_order_titles_facts_and_date_window(cli, lang, summary):
    args = ["--list", "-days", "36500", "-query", "provider:codex", "--lang", lang]
    if not summary:
        args.append("--no-metadata-summary")
    cli.parity(*args)
    cli.parity("--list", "-d", "1", "-q", "provider:codex", "--lang", lang)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("uri_prefix", ["codex://", "codex://threads/"])
def test_head_and_uri_prefix(cli, lang, uri_prefix):
    cli.parity(f"{uri_prefix}{IDENTITY}", "--head", "--lang", lang)


@pytest.mark.parametrize("size", [0, 120_000, 300_000, 2_000_000])
def test_large_text_and_bounded_metadata(cli, size):
    cli.write(
        [header(), message("user", "Start"), message("assistant", "中文😺\n" * size, stamp="2026-01-15T12:00:02Z")]
    )
    uri = f"codex://{IDENTITY}"
    cli.parity(uri, "--head", "--lang", "en")
    cli.parity(uri, "-format", "print", "--lang", "en")
    cli.parity(uri, "--format", "json", "--output", str(cli.root / "exports"), "--lang", "en", json_export=True)


@pytest.mark.parametrize("kind", ["ordinary", "reasoning", "developer", "missing-time", "unicode-controls"])
def test_message_assembly_and_json_schema(cli, kind):
    records = [header(cli_version="0.1", model_provider="openai"), message("user", "one")]
    if kind == "reasoning":
        records += [
            {
                "type": "response_item",
                "timestamp": STAMP,
                "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Think"}]},
            }
        ] * 2
    if kind == "developer":
        records.append(message("developer", "instructions without wrappers"))
    records += [message("assistant", "answer"), message("assistant", "answer"), message("assistant", "continued")]
    records.append(message("user", "\x1b[2J测试\u202e\n\tmore\rtext" if kind == "unicode-controls" else "two"))
    records.append(
        {"type": "event_msg", "payload": {"info": {"total_token_usage": {"input_tokens": "23", "output_tokens": 7}}}}
    )
    if kind == "missing-time":
        records[2].pop("timestamp")
    cli.write(records)
    cli.parity(
        f"codex://{IDENTITY}",
        "--format",
        "print,json,json",
        "--output",
        str(cli.root / "exports"),
        "--lang",
        "en",
        json_export=True,
    )


@pytest.mark.parametrize("title_source", ["second-message", "directory", "filename", "oversized-header", "index-last"])
def test_metadata_fallbacks(cli, title_source):
    index = cli.root / "sources" / "codex" / "session_index.jsonl"
    index.unlink()
    records = [header(), message("user", "first"), message("user", " 第二条\n" + "😺" * 110)]
    if title_source == "directory":
        records.pop()
    if title_source == "filename":
        records[0]["payload"].pop("id")
        records[0]["payload"]["timestamp"] = "bad-date"
    if title_source == "oversized-header":
        records = [header(padding="x" * 300_000)]
    if title_source == "index-last":
        index.write_text(
            "\n".join(json.dumps({"id": IDENTITY, "thread_name": name}) for name in ["Old", "  新\n名称  "])
        )
    cli.write(records)
    cli.parity(f"codex://{IDENTITY}", "--head", "--lang", "en")


@pytest.mark.parametrize("identity", ["UPPER", "folder/id", "con", "中文", "white space", "a" * 121])
def test_portable_export_identity(cli, identity):
    cli.write([header(identity), message("user", "ok")])
    cli.parity(
        f"codex://{identity}",
        "--format",
        "json",
        "-output",
        str(cli.root / "exports"),
        "--lang",
        "en",
        json_export=True,
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--search", "anything"],
        ["--list", "-q", "provider:unimplemented"],
        ["--collect"],
        [f"codex://{IDENTITY}", "--format", "xml"],
        [f"codex://{IDENTITY}", "--format", "json"],
    ],
)
def test_unimplemented_commands_fail_explicitly(cli, args):
    result = cli.run("rust", *args)
    assert result.returncode != 0
    assert result.stderr


def test_missing_session_and_source_protection(cli):
    assert cli.run("rust", "codex://missing", "--head").returncode == 1
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json", "--output", str(cli.root / "sources" / "codex"))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires privileges on Windows")
def test_export_symlink_cannot_modify_provider(cli):
    output = cli.root / "exports" / "codex"
    output.mkdir(parents=True)
    (output / f"{IDENTITY}.json").symlink_to(cli.source)
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json", "--output", str(output.parent))
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


def test_version_and_help_identify_experimental_scope(cli):
    cli.parity("--version")
    result = cli.run("rust", "--help")
    assert result.returncode == 0
    assert "Experimental Rust" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="Python does not apply TZ on Windows")
@pytest.mark.parametrize("zone", ["Asia/Shanghai", "America/New_York"])
def test_local_timezone_names(cli, zone):
    cli.environment["TZ"] = zone
    cli.parity(f"codex://{IDENTITY}", "--head", "--lang", "en")


def test_local_fallback_root(cli):
    local = cli.root / "data" / "codex"
    local.parent.mkdir(exist_ok=True)
    shutil.move(str(cli.root / "sources" / "codex" / "sessions"), local)
    cli.parity(f"codex://{IDENTITY}", "--head", "--lang", "en")


@pytest.mark.parametrize("days", ["0", "-1", "9999999999999999999999"])
def test_invalid_date_windows_are_argument_errors(cli, days):
    for candidate in ("python", "rust"):
        result = cli.run(candidate, "--list", "-q", "provider:codex", "-d", days)
        assert result.returncode == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions and unprivileged symlinks")
def test_private_export_preserves_existing_directory_permissions(cli):
    output = cli.root / "exports"
    output.mkdir(mode=0o755)
    before_mode = output.stat().st_mode
    args = [f"codex://{IDENTITY}", "--format", "json", "--output", str(output)]
    assert cli.run("rust", *args).returncode == 0
    assert output.stat().st_mode == before_mode
    assert (output / "codex").stat().st_mode & 0o777 == 0o700
    destination = output / "codex" / f"{IDENTITY}.json"
    destination.chmod(0o644)
    assert cli.run("rust", *args).returncode == 0
    assert destination.stat().st_mode & 0o777 == 0o600
    assert list((output / "codex").iterdir()) == [destination]
    shutil.rmtree(output)
    output.symlink_to(cli.root / "sources" / "codex" / "sessions", target_is_directory=True)
    before = cli.fixtures.source_manifest(cli.root)
    assert cli.run("rust", *args).returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before


def test_relative_export_path_matches_python(cli):
    cli.parity(f"codex://{IDENTITY}", "--format", "json", "--output", "exports", "--lang", "en", json_export=True)
