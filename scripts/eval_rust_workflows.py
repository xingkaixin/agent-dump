"""Paired workflow eval extending, without changing, the frozen P0 evaluator."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import gc
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import tempfile
import threading
import time

from benchmark_cases import Case, content_digest, expected_uris, require
from benchmark_cli import environment_metadata, files_digest, git_output, run_sample, summarize
from benchmark_fixtures import PROFILES, codex_id, create_fixture
from python_reference import command as reference_command, source_digest as reference_source_digest

ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "search-incremental-jsonl",
    "search-deleted-jsonl",
    "search-wal-sqlite",
    "search-four-providers",
    "collect-http-local",
    "collect-http-20ms",
)


def source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "sources").rglob("*")):
        if path.is_file() and not path.name.endswith("-shm"):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def add_providers(root: Path, count: int) -> set[str]:
    expected = set()
    for index in range(count):
        identity = f"extra-{index:06}"
        stamp = "2026-01-15T12:00:00+00:00"
        text = f"quartz extra provider synthetic {index} " + "中文正文 " * 32
        for provider, records in [
            (
                "claude",
                [
                    {
                        "type": "user",
                        "uuid": identity,
                        "timestamp": stamp,
                        "cwd": "/benchmark/extra",
                        "message": {"role": "user", "content": text},
                    }
                ],
            ),
            (
                "pi",
                [
                    {"type": "session", "id": identity, "version": 3, "cwd": "/benchmark/extra", "timestamp": stamp},
                    {
                        "type": "message",
                        "id": "entry",
                        "parentId": None,
                        "timestamp": stamp,
                        "message": {"role": "user", "content": text},
                    },
                ],
            ),
        ]:
            directory = (
                root
                / "sources"
                / provider
                / ("projects/benchmark" if provider == "claude" else "agent/sessions/benchmark")
            )
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{identity}.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
            os.utime(path, (1768478400, 1768478400))
            expected.add(f"{provider}://{identity}")
    return expected


@contextmanager
def local_model(delay: float):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            time.sleep(delay)
            text = (
                json.dumps(
                    {
                        "requests": ["Synthetic request"],
                        "decisions": ["Synthetic decision"],
                        "outcomes": ["Synthetic outcome"],
                    }
                )
                if "response_format" in body
                else "# Deterministic report\n\nSynthetic result."
            )
            data = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def evaluate(command: list[str], name: str, profile_name: str, root: Path) -> tuple[dict, dict]:
    profile = PROFILES[profile_name]
    environment = create_fixture(root, profile)
    # Release the frozen fixture's SQLite handles before timing and temporary-directory cleanup.
    gc.collect()
    environment.pop("PYTHONPATH", None)
    all_dates = ("-d", "36500")
    expected = expected_uris(profile, provider="codex", matching=True)
    mutation_count = min(32, profile.sessions_per_provider)
    if name.startswith("collect-http"):
        with local_model(0.02 if name.endswith("20ms") else 0) as (url, requests):
            config = Path(environment["APPDATA"]) if os.name == "nt" else Path(environment["HOME"]) / ".config"
            config = config / "agent-dump" / "config.toml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(
                f'[ai]\nprovider="openai"\nbase_url="{url}"\nmodel="synthetic"\napi_key="fixture"\n[logging]\nenabled=false\n',
                encoding="utf-8",
            )
            case = Case(
                name,
                (
                    "--collect",
                    "--since",
                    "20260115",
                    "--until",
                    "20260116",
                    "-q",
                    "provider:codex limit:16",
                    "--save",
                    "report.md",
                ),
                "extended",
            )
            before = source_digest(root)
            sample, output = run_sample(command, case, root, environment, timeout=120)
            require(source_digest(root) == before, "Collect modified a Provider source")
            report = (root / "report.md").read_text(encoding="utf-8")
            require(report == "# Deterministic report\n\nSynthetic result.", "Unexpected final report")
            require(len(requests) >= min(16, profile.sessions_per_provider + 1) + 1, "Missing summary requests")
            require(
                all(
                    body["model"] == "synthetic" and "untrusted_data" in body["messages"][-1]["content"]
                    for body in requests
                ),
                "Invalid request envelope",
            )
            validation = {
                "sources": before,
                "requests": len(requests),
                "prompt_sha256": content_digest(sorted(body["messages"][-1]["content"] for body in requests)),
                "report_sha256": content_digest(report),
            }
            return sample, validation
    if name == "search-four-providers":
        expected = expected_uris(profile, matching=True) | add_providers(root, profile.sessions_per_provider)
    with closing(sqlite3.connect(root / "sources" / "opencode.db")) as writer:
        if name == "search-wal-sqlite":
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        warmup = Case("prepare", ("--reindex", *all_dates), "reindex")
        before_warmup = source_digest(root)
        run_sample(command, warmup, root, environment, timeout=120)
        require(source_digest(root) == before_warmup, "Index warmup modified a Provider source")
        keyword = "quartz"
        scope = "provider:codex"
        if name == "search-incremental-jsonl":
            keyword = "delta-incremental"
            expected = set()
            for path in sorted((root / "sources" / "codex" / "sessions").rglob("*.jsonl"))[:mutation_count]:
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                identity = rows[0]["payload"]["id"]
                rows.append(
                    {
                        "type": "response_item",
                        "timestamp": "2026-01-16T12:00:00Z",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": keyword}],
                        },
                    }
                )
                path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
                expected.add(f"codex://{identity}")
        elif name == "search-deleted-jsonl":
            removed = 0
            for index in range(0, profile.sessions_per_provider + 1, 10):
                if removed == mutation_count:
                    break
                identity = codex_id(index)
                for path in (root / "sources" / "codex" / "sessions").rglob(f"*{identity}.jsonl"):
                    path.unlink()
                expected.remove(f"codex://{identity}")
                removed += 1
        elif name == "search-wal-sqlite":
            keyword = "delta-wal"
            scope = "provider:opencode"
            expected = {f"opencode://ses_bench_{index:06}" for index in range(mutation_count)}
            database = root / "sources" / "opencode.db"
            before_database = database.read_bytes()
            for index in range(mutation_count):
                writer.execute(
                    "UPDATE session_message SET data=? WHERE id=?",
                    (json.dumps({"text": keyword}), f"ses_bench_{index:06}_0"),
                )
            writer.commit()
            require(database.read_bytes() == before_database, "WAL fixture unexpectedly checkpointed")
        elif name == "search-four-providers":
            scope = "provider:codex,opencode,claudecode,pi"
        case = Case(name, ("--search", keyword, *all_dates, "-q", scope), "extended")
        before = source_digest(root)
        sample, output = run_sample(command, case, root, environment, timeout=120)
        found = re.findall(r"(?:codex|opencode|claude|pi)://[A-Za-z0-9_-]+", output)
        require(
            set(found) == expected and len(found) == len(expected),
            f"{name}: wrong result identities {len(found)} != {len(expected)}",
        )
        require(source_digest(root) == before, f"{name}: Provider source changed")
        return sample, {
            "sources": content_digest(list(writer.iterdump())) if name == "search-wal-sqlite" else before,
            "uris_sha256": content_digest(sorted(found)),
            "sessions": len(found),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-command", required=True)
    parser.add_argument("--python-command")
    parser.add_argument("--profile", choices=PROFILES, default="standard")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--case", choices=NAMES, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.repeats > 0 and args.warmups >= 0, "Invalid repetition count")
    commands = {
        "python": shlex.split(args.python_command) if args.python_command else reference_command(),
        "rust": shlex.split(args.rust_command),
    }
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_dirty": bool(git_output("status", "--porcelain")),
        "repeats": args.repeats,
        "warmups": args.warmups,
        "profile": args.profile,
        "environment": environment_metadata(),
        "python_source_sha256": reference_source_digest(),
        "frozen_evaluator_sha256": files_digest(list((ROOT / "scripts").glob("benchmark_*.py"))),
        "extension_sha256": files_digest([Path(__file__)]),
        "commands": commands,
        "cases": [],
    }
    for name in args.case or NAMES:
        samples = {candidate: [] for candidate in commands}
        validation = None
        for iteration in range(args.warmups + args.repeats):
            for candidate in ["python", "rust"] if iteration % 2 == 0 else ["rust", "python"]:
                with tempfile.TemporaryDirectory(prefix="agent-dump-workflow-eval-") as directory:
                    sample, checked = evaluate(commands[candidate], name, args.profile, Path(directory))
                    if validation is None:
                        validation = checked
                    require(
                        validation == checked,
                        f"{name}: result or source differs for {candidate}: {checked} != {validation}",
                    )
                    if iteration >= args.warmups:
                        samples[candidate].append(sample)
        summaries = {candidate: summarize(values) for candidate, values in samples.items()}
        speedup = summaries["python"]["wall_seconds"]["median"] / summaries["rust"]["wall_seconds"]["median"]
        report["cases"].append(
            {"name": name, "validation": validation, "samples": samples, "summary": summaries, "wall_speedup": speedup}
        )
        print(f"{name}: validated, {speedup:.2f}x", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Rust workflow extension eval",
        "",
        f"Profile: `{args.profile}`; {args.repeats} measured pairs, {args.warmups} warmup pairs.",
        "",
        "The original P0 evaluator is unchanged. HTTP timings include a deterministic loopback service, not a real model.",
        "",
        "| Case | Python median (ms) | Rust median (ms) | Speedup |",
        "| --- | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['name']} | {case['summary']['python']['wall_seconds']['median'] * 1000:.2f} | {case['summary']['rust']['wall_seconds']['median'] * 1000:.2f} | {case['wall_speedup']:.2f}× |"
        )
    args.output.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
