"""Compare workloads bound by sequential provider reads and LLM requests."""

import argparse
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict
import gc
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import statistics
import tempfile
import threading
import time

from benchmark_cases import Case, require
from benchmark_cli import environment_metadata, reset_outputs, run_sample, summarize
from benchmark_fixtures import Profile, create_fixture, source_manifest
from eval_rust_workflows import add_providers

ALL_DATES = ("-d", "36500")
COLLECT = {
    "collect-long-session": (Profile(3, 4, 256, 128_000), "insight"),
    "collect-tree-merge": (Profile(64, 4, 256, 256), "pm"),
    "collect-final-split": (Profile(128, 4, 256, 256), "insight"),
}
SEARCH = {
    "list-codex": (("--list", *ALL_DATES, "-q", "provider:codex", "--json"), False, False),
    "list-opencode": (("--list", *ALL_DATES, "-q", "provider:opencode", "--json"), False, False),
    "list-claude": (("--list", *ALL_DATES, "-q", "provider:claudecode", "--json"), False, False),
    "list-pi": (("--list", *ALL_DATES, "-q", "provider:pi", "--json"), False, False),
    "list-all": (("--list", *ALL_DATES, "--json"), False, False),
    "search-role-fallback": (("--search", "quartz", *ALL_DATES, "-q", "role:user", "--json"), False, False),
    "search-warm": (("--search", "quartz", *ALL_DATES, "--json"), True, False),
    "search-locate-warm": (("--search", "quartz", "--locate", *ALL_DATES, "--json"), True, False),
    "reindex-cold": (("--reindex", *ALL_DATES), False, True),
}
NAMES = (*COLLECT, *SEARCH)


@contextmanager
def local_model(delay: float):
    stats = {"in_flight": 0, "peak": 0, "connections": 0}
    phases: dict[str, dict[str, float]] = {}
    lock = threading.Lock()
    counter = iter(range(1 << 30))

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 keeps connections open so the connection count shows client reuse.
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            with lock:
                stats["connections"] += 1
            super().handle()

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            prompt = body["messages"][-1]["content"]
            phase = (
                "final"
                if "response_format" not in body
                else "group_merge"
                if "collect://group-level" in prompt
                else "session_merge"
                if "#summary-" in prompt
                else "chunk"
            )
            started = time.perf_counter()
            with lock:
                stats["in_flight"] += 1
                stats["peak"] = max(stats["peak"], stats["in_flight"])
                number = next(counter)
            schema = None
            try:
                time.sleep(delay)
                schema = body.get("response_format", {}).get("json_schema", {}).get("schema")
                if schema:
                    # Seven distinct items per field make every multi-payload merge exceed the compression limit.
                    text = json.dumps(
                        {
                            field: [f"{field} {number:06d}-{item} synthetic finding " + "x" * 40 for item in range(7)]
                            for field in schema["properties"]
                        }
                    )
                else:
                    text = "# Deterministic report\n\nSynthetic result."
                data = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                ended = time.perf_counter()
                with lock:
                    stats["in_flight"] -= 1
                    span = phases.setdefault(phase, {"requests": 0, "first": started, "last": ended})
                    span["requests"] += 1
                    span["first"] = min(span["first"], started)
                    span["last"] = max(span["last"], ended)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", stats, phases
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def write_config(environment: dict[str, str], url: str) -> None:
    base = Path(environment["APPDATA"]) if os.name == "nt" else Path(environment["HOME"]) / ".config"
    config = base / "agent-dump" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'[ai]\nprovider="openai"\nbase_url="{url}"\nmodel="synthetic"\napi_key="fixture"\n'
        "[collect]\nsummary_concurrency=4\n[logging]\nenabled=false\n",
        encoding="utf-8",
    )


def measure(
    commands: dict[str, list[str]], repeats: int, sample: Callable[[list[str]], tuple[dict, dict]]
) -> tuple[dict, dict]:
    samples: dict[str, list[dict]] = {label: [] for label in commands}
    reference: dict | None = None
    for iteration in range(repeats + 1):
        order = list(commands) if iteration % 2 == 0 else list(reversed(commands))
        for label in order:
            metrics, checked = sample(commands[label])
            if reference is None:
                reference = checked
            require(checked == reference, f"result differs for {label}: {checked} != {reference}")
            if iteration:
                samples[label].append(metrics)
    if reference is None:
        raise ValueError("benchmark produced no samples")
    return samples, reference


def collect_case(name: str, commands: dict[str, list[str]], repeats: int, delay: float) -> dict:
    profile, mode = COLLECT[name]
    with tempfile.TemporaryDirectory(prefix="agent-dump-sequential-io-") as temporary:
        root = Path(temporary).resolve()
        environment = create_fixture(root, profile)
        gc.collect()
        before = source_manifest(root)
        case = Case(
            name,
            (
                "--collect",
                "--collect-mode",
                mode,
                "--since",
                "20260115",
                "--until",
                "20260116",
                "-q",
                "provider:codex",
                "--save",
                "report.md",
            ),
            "collect",
        )

        def sample(command: list[str]) -> tuple[dict, dict]:
            with local_model(delay) as (url, stats, phases):
                write_config(environment, url)
                metrics, _ = run_sample(command, case, root, environment, timeout=600)
            report = (root / "report.md").read_text(encoding="utf-8")
            require(report.startswith("# Deterministic report"), f"{name}: unexpected report")
            metrics.update(
                peak_in_flight=stats["peak"],
                connections=stats["connections"],
                phase_seconds={name: span["last"] - span["first"] for name, span in phases.items()},
            )
            return metrics, {
                "requests": {name: span["requests"] for name, span in sorted(phases.items())},
                "report_sha256": hashlib.sha256(report.encode()).hexdigest(),
            }

        samples, reference = measure(commands, repeats, sample)
        require(source_manifest(root) == before, f"{name}: Provider sources changed")
    if name == "collect-final-split":
        require(reference["requests"]["final"] > 1, f"{name}: final report was not split")
    return {"name": name, "profile": asdict(profile), "mode": mode, "validation": reference, "samples": samples}


def search_cases(names: list[str], commands: dict[str, list[str]], repeats: int) -> list[dict]:
    profile = Profile(500, 20, 256, 256 * 1024)
    results = []
    with tempfile.TemporaryDirectory(prefix="agent-dump-sequential-io-") as temporary:
        root = Path(temporary).resolve()
        environment = create_fixture(root, profile)
        add_providers(root, profile.sessions_per_provider)
        gc.collect()
        before = source_manifest(root)
        prepare = Case("prepare", ("--reindex", *ALL_DATES), "reindex")
        for name in names:
            args, warm, cold = SEARCH[name]
            case = Case(name, args, "search")
            reset_outputs(root, reset_index=True)
            if warm:
                run_sample(commands["baseline"], prepare, root, environment, timeout=600)

            def sample(command: list[str], case: Case = case, cold: bool = cold) -> tuple[dict, dict]:
                if cold:
                    reset_outputs(root, reset_index=True)
                metrics, output = run_sample(command, case, root, environment, timeout=600)
                return metrics, {"stdout_sha256": hashlib.sha256(output.encode()).hexdigest()}

            samples, reference = measure(commands, repeats, sample)
            results.append({"name": name, "args": list(args), "validation": reference, "samples": samples})
        require(source_manifest(root) == before, "Provider sources changed")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--llm-delay", type=float, default=0.2)
    parser.add_argument("--case", choices=NAMES, action="append")
    args = parser.parse_args()
    if args.repeats < 1 or args.llm_delay < 0:
        parser.error("repeats must be positive and llm-delay non-negative")
    binaries = {"baseline": args.baseline} | ({"candidate": args.candidate} if args.candidate else {})
    commands = {label: [str(path.resolve())] for label, path in binaries.items()}
    names = args.case or list(NAMES)
    cases = [collect_case(name, commands, args.repeats, args.llm_delay) for name in names if name in COLLECT]
    cases += search_cases([name for name in names if name in SEARCH], commands, args.repeats)
    for case in cases:
        case["summary"] = {label: summarize(values) for label, values in case["samples"].items()}
        medians = {label: summary["wall_seconds"]["median"] * 1000 for label, summary in case["summary"].items()}
        first = case["samples"]["baseline"][0]
        extra = {key: first[key] for key in ("peak_in_flight", "connections") if key in first}
        if "phase_seconds" in first:
            for label, values in case["samples"].items():
                extra[f"{label}_phase_ms"] = {
                    phase: round(statistics.median(value["phase_seconds"][phase] for value in values) * 1000)
                    for phase in first["phase_seconds"]
                }
        print(case["name"], {label: round(value, 1) for label, value in medians.items()}, case["validation"], extra)
    report = {
        "environment": environment_metadata(),
        "repeats": args.repeats,
        "llm_delay_seconds": args.llm_delay,
        "executables": {
            label: {"path": command[0], "sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()}
            for label, command in commands.items()
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
