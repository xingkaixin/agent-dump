"""Differential CLI contracts against the unchanged Python reference, using only synthetic sources."""

from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUST = ROOT / "rust" / "target" / "debug" / ("agent-dump.exe" if os.name == "nt" else "agent-dump")
IDENTITY = "019c213e-c251-73a3-af66-000000000000"
STAMP = "2026-01-15T12:00:00+00:00"


@dataclass
class CliFixture:
    root: Path
    environment: dict[str, str]
    source: Path
    fixtures: Any

    def run(self, candidate: str, *args: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-m", "agent_dump"] if candidate == "python" else [str(RUST)]
        return subprocess.run(  # noqa: S603
            [*command, *args], cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=30
        )

    def write(self, records: list[dict[str, Any]], *, suffix: bytes = b"") -> None:
        self.source.write_bytes(
            b"".join(json.dumps(record, ensure_ascii=False).encode() + b"\n" for record in records) + suffix
        )
        os.utime(self.source, (1768478400, 1768478400))

    def parity(self, *args: str, json_export: bool = False) -> None:
        before = self.fixtures.source_manifest(self.root)
        results = []
        outputs = []
        for candidate in ("python", "rust"):
            output = self.root / "exports"
            shutil.rmtree(output, ignore_errors=True)
            result = self.run(candidate, *args)
            assert result.returncode == 0, result.stdout + result.stderr
            results.append((result.stdout, result.stderr))
            if json_export:
                files = list(output.rglob("*.json"))
                assert len(files) == 1
                outputs.append((files[0].relative_to(output), json.loads(files[0].read_text())))
                if os.name != "nt":
                    assert files[0].stat().st_mode & 0o777 == 0o600
            assert self.fixtures.source_manifest(self.root) == before
        assert results[0] == results[1]
        if json_export:
            assert outputs[0] == outputs[1]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    assert RUST.is_file(), "Run cargo build --locked --manifest-path rust/Cargo.toml before this suite"
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    fixtures = importlib.import_module("benchmark_fixtures")
    environment = fixtures.create_fixture(tmp_path, fixtures.PROFILES["smoke"])
    environment["PYTHONPATH"] = str(ROOT / "src")
    source = next((tmp_path / "sources" / "codex" / "sessions").rglob(f"*-{IDENTITY}.jsonl"))
    return CliFixture(tmp_path, environment, source, fixtures)


def header(identity: str = IDENTITY, **fields: Any) -> dict[str, Any]:
    return {"type": "session_meta", "payload": {"id": identity, "timestamp": STAMP, "cwd": "/project", **fields}}


def message(role: str, text: str, *, stamp: str = STAMP) -> dict[str, Any]:
    return {
        "type": "response_item",
        "timestamp": stamp,
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": "output_text" if role == "assistant" else "input_text", "text": text}],
        },
    }


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


def test_malformed_records_and_active_tail(cli):
    cli.write([header(), message("user", "retained")], suffix=b'not-json\n[]\n{"partial":')
    before = cli.fixtures.source_manifest(cli.root)
    outputs = []
    for candidate in ("python", "rust"):
        result = cli.run(
            candidate, f"codex://{IDENTITY}", "--format", "json", "--output", str(cli.root / "exports"), "--lang", "en"
        )
        assert result.returncode == 0
        assert "2" in result.stdout + result.stderr
        outputs.append(json.loads(next((cli.root / "exports").rglob("*.json")).read_text()))
    assert outputs[0] == outputs[1]
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "function_call", "name": "exec_command", "call_id": "1", "arguments": "{}"},
        {"type": "custom_tool_call", "name": "apply_patch", "input": "patch"},
        {"type": "function_call_output", "call_id": "1", "output": "done"},
        {"type": "future_message_kind", "text": "must not disappear"},
        message("user", "<skill>content</skill>")["payload"],
        message("user", "<INSTRUCTIONS>context</INSTRUCTIONS>")["payload"],
        message("assistant", "<proposed_plan>plan</proposed_plan>")["payload"],
        {"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": "synthetic"}]},
    ],
)
def test_unimplemented_messages_fail_before_output(cli, payload):
    cli.write([header(), message("user", "prefix"), {"type": "response_item", "payload": payload}])
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json,print", "--output", str(cli.root / "exports"))
    assert result.returncode == 1
    assert "Rust P1 does not yet support" in result.stderr
    assert result.stdout == ""
    assert not (cli.root / "exports").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--search", "anything"],
        ["--list"],
        ["--list", "-q", "provider:opencode"],
        ["--collect"],
        [f"codex://{IDENTITY}", "--format", "md"],
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
    assert "Experimental Rust P1" in result.stdout


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
