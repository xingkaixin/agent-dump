"""Isolated subprocess fixtures shared by Rust CLI contract tests."""

from dataclasses import dataclass
import gc
import importlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUST = Path(
    os.environ.get(
        "AGENT_DUMP_TEST_BINARY",
        ROOT / "target" / "release" / ("agent-dump.exe" if os.name == "nt" else "agent-dump"),
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

    def run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [str(RUST), *args],
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


def make_cli(tmp_path, monkeypatch):
    assert RUST.is_file(), "Run cargo build --locked --release before this suite"
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    fixtures = importlib.import_module("benchmark_fixtures")
    environment = fixtures.create_fixture(tmp_path, fixtures.PROFILES["smoke"])
    if os.name == "nt":
        # The frozen benchmark fixture leaves SQLite handles for cyclic GC.
        gc.collect()
    environment.pop("PYTHONPATH", None)
    source = next((tmp_path / "sources" / "codex" / "sessions").rglob(f"*-{IDENTITY}.jsonl"))
    return CliFixture(tmp_path, environment, source, fixtures)


def header(identity: str = IDENTITY, **fields: Any) -> dict[str, Any]:
    return {"type": "session_meta", "payload": {"id": identity, "timestamp": STAMP, "cwd": "/project", **fields}}


def write_jsonl(path: Path, records: list[dict[str, Any]], *, suffix: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json.dumps(record, ensure_ascii=False).encode() + b"\n" for record in records) + suffix)
    os.utime(path, (1768478400, 1768478400))
    return path


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
