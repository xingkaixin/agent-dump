"""Isolated subprocess fixtures shared by Rust/Python CLI differential tests."""

from dataclasses import dataclass
import gc
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUST = Path(
    os.environ.get(
        "AGENT_DUMP_TEST_BINARY",
        ROOT / "rust" / "target" / "release" / ("agent-dump.exe" if os.name == "nt" else "agent-dump"),
    )
).resolve()
IDENTITY = "019c213e-c251-73a3-af66-000000000000"
STAMP = "2026-01-15T12:00:00+00:00"


@dataclass
class CliFixture:
    root: Path
    environment: dict[str, str]
    source: Path
    fixtures: Any

    def run(self, candidate: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-m", "agent_dump"] if candidate == "python" else [str(RUST)]
        return subprocess.run(  # noqa: S603
            [*command, *args],
            cwd=self.root,
            env=self.environment,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def write(self, records: list[dict[str, Any]], *, suffix: bytes = b"") -> None:
        self.source.write_bytes(
            b"".join(json.dumps(record, ensure_ascii=False).encode() + b"\n" for record in records) + suffix
        )
        os.utime(self.source, (1768478400, 1768478400))

    def parity(self, *args: str, json_export: bool = False, formats: tuple[str, ...] = (), exit_code: int = 0) -> None:
        before = self.fixtures.source_manifest(self.root)
        results = []
        outputs = []
        for candidate in ("python", "rust"):
            output = self.root / "exports"
            shutil.rmtree(output, ignore_errors=True)
            result = self.run(candidate, *args)
            assert result.returncode == exit_code, result.stdout + result.stderr
            results.append((result.stdout, result.stderr))
            files = sorted(path for path in output.rglob("*") if path.is_file())
            expected = formats or (("json",) if json_export else ())
            if expected:
                suffixes = {"json": ".json", "markdown": ".md", "raw": ".jsonl", "raw-json": ".json"}
                assert sorted(path.suffix for path in files) == sorted(suffixes[item] for item in expected)
            outputs.append(
                {
                    path.relative_to(output): json.loads(path.read_text())
                    if path.suffix == ".json"
                    else path.read_bytes()
                    for path in files
                }
            )
            if os.name != "nt":
                assert all(path.stat().st_mode & 0o777 == 0o600 for path in files)
            assert self.fixtures.source_manifest(self.root) == before
        assert results[0] == results[1], results
        assert outputs[0] == outputs[1], outputs


def make_cli(tmp_path, monkeypatch):
    assert RUST.is_file(), "Run cargo build --locked --release from rust/ before this suite"
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    fixtures = importlib.import_module("benchmark_fixtures")
    environment = fixtures.create_fixture(tmp_path, fixtures.PROFILES["smoke"])
    if os.name == "nt":
        # The frozen benchmark fixture leaves SQLite handles for cyclic GC.
        gc.collect()
    environment["PYTHONPATH"] = str(ROOT / "src")
    source = next((tmp_path / "sources" / "codex" / "sessions").rglob(f"*-{IDENTITY}.jsonl"))
    return CliFixture(tmp_path, environment, source, fixtures)


def header(identity: str = IDENTITY, **fields: Any) -> dict[str, Any]:
    return {"type": "session_meta", "payload": {"id": identity, "timestamp": STAMP, "cwd": "/project", **fields}}


def write_jsonl(path: Path, records: list[dict[str, Any]], *, suffix: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json.dumps(record, ensure_ascii=False).encode() + b"\n" for record in records) + suffix)
    os.utime(path, (1768478400, 1768478400))
    return path


def provider_export(cli: CliFixture, uri: str, provider: str, *, lang: str = "en") -> dict[str, Any]:
    cli.parity(
        uri, "--format", "json,md,raw,print", "--output", "exports", "--lang", lang, formats=("json", "markdown", "raw")
    )
    return json.loads(next((cli.root / "exports" / provider).glob("*.json")).read_text())


def message(role: str | None, text: str, *, stamp: str = STAMP) -> dict[str, Any]:
    return {
        "type": "response_item",
        "timestamp": stamp,
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": "output_text" if role == "assistant" else "input_text", "text": text}],
        },
    }


def record(kind, **fields):
    return {"type": "response_item", "timestamp": STAMP, "payload": {"type": kind, **fields}}


def call(name="exec_command", identity="one", arguments=None, *, custom=False):
    return record(
        "custom_tool_call" if custom else "function_call",
        name=name,
        call_id=identity,
        **{"input" if custom else "arguments": arguments if arguments is not None else {"cmd": "echo synthetic"}},
    )


def output(value="done", identity="one", *, custom=False):
    return record("custom_tool_call_output" if custom else "function_call_output", call_id=identity, output=value)


def reasoning(text="Thinking"):
    return record("reasoning", summary=[{"type": "summary_text", "text": text}])


def export_parity(cli, records, *, lang="en", formats="json,md,raw,print"):
    cli.write([header(cli_version="1.0", model_provider="openai"), *records])
    cli.parity(
        f"codex://{IDENTITY}",
        "--format",
        formats,
        "--output",
        "exports",
        "--lang",
        lang,
        formats=("json", "markdown", "raw"),
    )
    return json.loads((cli.root / "exports" / "codex" / f"{IDENTITY}.json").read_text())
