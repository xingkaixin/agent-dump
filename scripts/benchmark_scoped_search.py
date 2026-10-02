"""Compare scoped searches on isolated JSONL/SQLite sources with exact output checks."""

import argparse
from contextlib import closing
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from benchmark_cases import Case, expected_uris, require
from benchmark_cli import ROOT, environment_metadata, reset_outputs, run_sample, summarize
from benchmark_fixtures import Profile, codex_id, create_fixture, source_manifest


def scope_fixture(root: Path, profile: Profile) -> set[str]:
    selected = set()
    for path in (root / "sources/codex/sessions").rglob("*.jsonl"):
        lines = path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        identity = header["payload"]["id"]
        if int(identity[-12:], 16) % 100 == 0:
            header["payload"]["cwd"] = "/benchmark/selected"
            lines[0] = json.dumps(header)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            selected.add(f"codex://{identity}")
    with closing(sqlite3.connect(root / "sources/opencode.db")) as connection:
        for index in range(0, profile.sessions_per_provider, 100):
            identity = f"ses_bench_{index:06d}"
            connection.execute("UPDATE session_v2 SET directory = ? WHERE id = ?", ("/benchmark/selected", identity))
            selected.add(f"opencode://{identity}")
        connection.commit()
    require(f"codex://{codex_id(0)}" in selected, "missing selected JSONL fixture")
    return selected


def validate(output: str, expected: set[str]) -> None:
    payload = json.loads(output)
    require(payload["schema_version"] == 1 and payload["kind"] == "search", "unexpected search envelope")
    require(payload["status"] == "ok", "search reported incomplete results")
    require(not payload["failed_providers"] and not payload["failed_sessions"], "search reported failures")
    actual = [item["uri"] for item in payload["data"]]
    require(set(actual) == expected and len(actual) == len(expected), "search scope differs from fixture")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sessions", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.sessions < 1 or args.repeats < 1:
        parser.error("sessions and repeats must be positive")
    commands = {name: [str(getattr(args, name).resolve())] for name in ("baseline", "candidate")}
    profile = Profile(args.sessions, 8, 1024, 1024)
    catalog = json.loads((ROOT / "resources/locales/en.json").read_text(encoding="utf-8"))
    progress = "".join(
        catalog["INDEX_UPDATE_PROGRESS"].format(agent=provider, count=count) + "\n"
        for provider, count in (("OpenCode", args.sessions), ("Codex", args.sessions + 1))
        if count >= 10
    )
    report = {
        "environment": environment_metadata(),
        "profile": asdict(profile),
        "repeats": args.repeats,
        "warmups_per_binary": 1,
        "executables": {
            name: {"path": command[0], "sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()}
            for name, command in commands.items()
        },
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="agent-dump-scoped-search-") as temporary:
        root = Path(temporary).resolve()
        environment = create_fixture(root, profile)
        gc.collect()
        selected = scope_fixture(root, profile)
        before = source_manifest(root)
        all_uris = expected_uris(profile)
        prepare = Case("prepare", ("--search", "payload", "--days", "36500", "--json"), "search")
        workloads = [
            ("empty-cold", "payload", "path:/benchmark/missing", True, set()),
            ("narrow-cold", "payload", "path:/benchmark/selected", True, selected),
            ("narrow-warm", "payload", "path:/benchmark/selected", False, selected),
            ("broad-warm", "payload", "path:/benchmark", False, all_uris),
            ("cjk-narrow-warm", "中文", "path:/benchmark/selected", False, selected),
            ("literal-narrow-warm", "q", "path:/benchmark/selected", False, selected),
        ]
        for name, keyword, scope, cold, expected in workloads:
            case = Case(name, ("--search", keyword, "--query", scope, "--days", "36500", "--json"), "search")
            reset_outputs(root, reset_index=True)
            if not cold:
                _, output = run_sample(commands["baseline"], prepare, root, environment, timeout=60)
                validate(output, all_uris)
            samples: dict[str, list[dict]] = {"baseline": [], "candidate": []}
            reference = None
            for iteration in range(args.repeats + 1):
                order = ("baseline", "candidate") if iteration % 2 == 0 else ("candidate", "baseline")
                for label in order:
                    if cold:
                        reset_outputs(root, reset_index=True)
                    metrics, output = run_sample(commands[label], case, root, environment, timeout=60)
                    validate(output, expected)
                    if reference is None:
                        reference = output
                    require(output == reference, f"{name}: stdout differs between binaries or repetitions")
                    diagnostics = (root / "stderr.txt").read_text(encoding="utf-8")
                    allowed = {"", progress} if not expected else {progress if cold else ""}
                    require(diagnostics in allowed, f"{name}: unexpected diagnostics: {diagnostics}")
                    if label == "candidate" and not expected:
                        require(not (root / "cache/agent-dump/search-index.db").exists(), "empty scope opened an index")
                    if iteration:
                        samples[label].append(metrics)
            if reference is None:
                raise ValueError("benchmark produced no output")
            report["cases"].append(
                {
                    "name": name,
                    "args": case.args,
                    "sessions": len(expected),
                    "stdout_sha256": hashlib.sha256(reference.encode()).hexdigest(),
                    "samples": samples,
                    "summary": {label: summarize(values) for label, values in samples.items()},
                }
            )
            print(
                name,
                {
                    label: round(summarize(values)["wall_seconds"]["median"] * 1000, 2)
                    for label, values in samples.items()
                },
                flush=True,
            )
        require(source_manifest(root) == before, "benchmark modified Provider sources")
        report["source_manifest"] = before
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
