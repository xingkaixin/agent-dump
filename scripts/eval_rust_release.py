"""Interleave the frozen P0 workloads without changing their fixtures or validator."""

import argparse
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import tempfile
from typing import Any

from benchmark_cases import Case, cases, require, validate
from benchmark_cli import (
    SCHEMA_VERSION,
    compare_reports,
    environment_metadata,
    files_digest,
    git_output,
    markdown_report,
    reset_outputs,
    run_sample,
    summarize,
)
from benchmark_fixtures import FIXTURE_VERSION, PROFILES, create_fixture, source_manifest
from python_reference import command as reference_command, source_digest

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-command", required=True)
    parser.add_argument("--profile", choices=PROFILES, default="standard")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.repeats > 0 and args.warmups >= 0, "Invalid repetition count")
    profile = PROFILES[args.profile]
    commands = {"python": reference_command(), "rust": shlex.split(args.rust_command)}
    reports: dict[str, Any] = {}
    with ExitStack() as stack:
        contexts = {}
        for candidate, command in commands.items():
            root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="agent-dump-paired-"))).resolve()
            environment = create_fixture(root, profile)
            environment.pop("PYTHONPATH", None)
            contexts[candidate] = (root, environment)
            _, version = run_sample(command, Case("version", ("--version",), "version"), root, environment, timeout=180)
            executable = Path(command[0])
            reports[candidate] = {
                "schema_version": SCHEMA_VERSION,
                "fixture_version": FIXTURE_VERSION,
                "label": f"{candidate}-p6-{args.profile}",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "git_commit": git_output("rev-parse", "HEAD"),
                "git_dirty": bool(git_output("status", "--porcelain")),
                "python_source_sha256": source_digest(),
                "evaluator_sha256": files_digest(list((ROOT / "scripts").glob("benchmark_*.py"))),
                "orchestrator_sha256": files_digest([Path(__file__)]),
                "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
                "command": [value.replace(str(ROOT), "<REPO>") for value in command],
                "cli_version": version.strip(),
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "executable_bytes": executable.stat().st_size,
                "environment": environment_metadata(),
                "profile": args.profile,
                "profile_settings": asdict(profile),
                "repeats": args.repeats,
                "warmups": args.warmups,
                "schedule": "Alternate Python/Rust order every pair, including warmups; separate fixture/index per candidate",
                "source_manifest": source_manifest(root),
                "cases": [],
            }
        for case in cases(profile):
            for candidate, command in commands.items():
                root, environment = contexts[candidate]
                reset_outputs(root, reset_index=True)
                if case.index == "warm":
                    prepare = Case("prepare-index", ("--reindex", "-d", "36500"), "reindex")
                    sample, output = run_sample(command, prepare, root, environment, timeout=180)
                    validate(prepare, profile, root, output, sample["exit_code"])
            samples: dict[str, list[dict]] = {candidate: [] for candidate in commands}
            checked = None
            for iteration in range(args.repeats + args.warmups):
                for candidate in ("python", "rust") if iteration % 2 == 0 else ("rust", "python"):
                    root, environment = contexts[candidate]
                    reset_outputs(root, reset_index=case.index == "empty")
                    sample, output = run_sample(commands[candidate], case, root, environment, timeout=180)
                    validation = validate(case, profile, root, output, sample["exit_code"])
                    if checked is None:
                        checked = validation
                    require(checked == validation, f"{case.name}: {candidate} output differs")
                    if iteration >= args.warmups:
                        samples[candidate].append(sample)
            for candidate, values in samples.items():
                root, _ = contexts[candidate]
                require(source_manifest(root) == reports[candidate]["source_manifest"], "Provider source changed")
                reports[candidate]["cases"].append(
                    {
                        "name": case.name,
                        "args": [*case.args, "--lang", "en"],
                        "stdin": case.stdin,
                        "index": case.index,
                        "validation": checked,
                        "samples": values,
                        "summary": summarize(values),
                    }
                )
            print(f"{case.name}: validated", flush=True)
    reports["rust"]["comparison"] = compare_reports(reports["python"], reports["rust"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for candidate, report in reports.items():
        output = args.output if candidate == "rust" else args.output.with_stem(args.output.stem + "-python")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")


if __name__ == "__main__":
    main()
