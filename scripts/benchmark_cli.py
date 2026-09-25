"""Run validated CLI benchmarks against Python or an arbitrary native executable."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from typing import Any

from benchmark_cases import Case, cases, require, validate
from benchmark_fixtures import FIXTURE_VERSION, PROFILES, Profile, create_fixture, source_manifest
from python_reference import source_digest as reference_source_digest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=10).strip()  # noqa: S603,S607


def files_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def environment_metadata() -> dict[str, Any]:
    cpu = platform.processor()
    if sys.platform == "darwin":
        cpu = subprocess.check_output(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()  # noqa: S603
    elif sys.platform == "linux":
        cpu = next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            cpu,
        )
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "collector_python": platform.python_version(),
        "fixture_sqlite": sqlite3.sqlite_version,
        "timezone": "UTC",
        "locale": "en",
        "filesystem_cache": "uncontrolled; fixture creation and warmups populate OS page cache",
        "rss_method": "fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum"
        if sys.platform in {"darwin", "linux"}
        else "unavailable",
    }


def run_sample(
    command: list[str], case: Case, root: Path, environment: dict[str, str], *, timeout: float
) -> tuple[dict[str, Any], str]:
    metrics = root / "metrics.json"
    collector = [
        sys.executable,
        str(ROOT / "scripts" / "benchmark_process.py"),
        "--metrics",
        str(metrics),
        "--timeout",
        str(timeout),
        "--",
        *command,
        *case.args,
        "--lang",
        "en",
    ]
    with (
        (root / "stdout.txt").open("w", encoding="utf-8") as stdout,
        (root / "stderr.txt").open("w", encoding="utf-8") as stderr,
    ):
        result = subprocess.run(  # noqa: S603
            collector,
            input=case.stdin,
            text=True,
            cwd=root,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout + 15,
        )
    diagnostics = (root / "stderr.txt").read_text(encoding="utf-8")
    require(result.returncode == 0, f"collector failed for {case.name}: {diagnostics[-2000:]}")
    sample = json.loads(metrics.read_text(encoding="utf-8"))
    require(sample["exit_code"] == 0, f"{case.name}: exit {sample['exit_code']}\n{diagnostics[-2000:]}")
    output = (root / "stdout.txt").read_text(encoding="utf-8")
    sample.update(stdout_bytes=(root / "stdout.txt").stat().st_size, stderr_bytes=(root / "stderr.txt").stat().st_size)
    return sample, output


def reset_outputs(root: Path, *, reset_index: bool) -> None:
    if (root / "exports").exists():
        shutil.rmtree(root / "exports")
    if reset_index:
        if (root / "cache").exists():
            shutil.rmtree(root / "cache")
        (root / "cache").mkdir()


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        name: {
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0,
        }
        for name in ("wall_seconds", "user_seconds", "system_seconds", "peak_rss_bytes")
        if (values := [sample[name] for sample in samples if name in sample])
    }


def run_case(
    command: list[str],
    case: Case,
    profile: Profile,
    root: Path,
    environment: dict[str, str],
    *,
    repeats: int,
    warmups: int,
    timeout: float,
) -> dict[str, Any]:
    reset_outputs(root, reset_index=True)
    if case.index == "warm":
        preparation = Case("prepare-index", ("--reindex", "-d", "36500"), "reindex")
        sample, output = run_sample(command, preparation, root, environment, timeout=timeout)
        validate(preparation, profile, root, output, sample["exit_code"])
    samples = []
    expected_check = None
    for iteration in range(warmups + repeats):
        reset_outputs(root, reset_index=case.index == "empty")
        sample, output = run_sample(command, case, root, environment, timeout=timeout)
        checked = validate(case, profile, root, output, sample["exit_code"])
        if expected_check is None:
            expected_check = checked
        require(checked == expected_check, f"{case.name}: output changed between repetitions")
        if iteration >= warmups:
            samples.append(sample)
    return {
        "name": case.name,
        "args": [*case.args, "--lang", "en"],
        "stdin": case.stdin,
        "index": case.index,
        "validation": expected_check,
        "samples": samples,
        "summary": summarize(samples),
    }


def compare_reports(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    for field in (
        "schema_version",
        "fixture_version",
        "profile",
        "profile_settings",
        "source_manifest",
        "evaluator_sha256",
    ):
        require(baseline[field] == current[field], f"cannot compare different {field}")
    for field in ("system", "release", "machine", "cpu", "logical_cpus", "rss_method"):
        require(
            baseline["environment"][field] == current["environment"][field], f"cannot compare different host {field}"
        )
    previous = {case["name"]: case for case in baseline["cases"]}
    require(set(previous) == {case["name"] for case in current["cases"]}, "cannot compare different case sets")
    comparisons = []
    for case in current["cases"]:
        reference = previous[case["name"]]
        for field in ("args", "stdin", "index", "validation"):
            require(reference[field] == case[field], f"{case['name']}: {field} differs from baseline")
        before = reference["summary"]["wall_seconds"]["median"]
        after = case["summary"]["wall_seconds"]["median"]
        row = {"name": case["name"], "wall_speedup": before / after, "wall_change_percent": (after / before - 1) * 100}
        if "peak_rss_bytes" in reference["summary"] and "peak_rss_bytes" in case["summary"]:
            before_rss = reference["summary"]["peak_rss_bytes"]["median"]
            row["rss_change_percent"] = (case["summary"]["peak_rss_bytes"]["median"] / before_rss - 1) * 100
        comparisons.append(row)
    return comparisons


def markdown_report(report: dict[str, Any]) -> str:
    environment = report["environment"]
    lines = [
        f"# CLI benchmark: {report['label']}",
        "",
        f"- Recorded: {report['recorded_at']}",
        f"- Reference checkout: `{report['git_commit']}`; Python source SHA-256: `{report['python_source_sha256']}`",
        f"- Command: `{shlex.join(report['command'])}`; version: `{report['cli_version']}`",
        f"- Host: {environment['system']} {environment['release']} / {environment['machine']} / {environment['cpu']}",
        f"- Profile: `{report['profile']}`; fixture version: {report['fixture_version']}",
        f"- Sources: {report['source_manifest']['files']} files, {report['source_manifest']['bytes']:,} bytes",
        f"- Repetitions: {report['repeats']}; warmups per case: {report['warmups']}",
        "- Every sample passed its workload checks; source bytes remained unchanged.",
        f"- OS page cache: {environment['filesystem_cache']}",
        f"- RSS: {environment['rss_method']}",
        "",
        "| Case | Median ms | Min–max ms | Median peak RSS MiB |",
        "| --- | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        wall = case["summary"]["wall_seconds"]
        rss = case["summary"].get("peak_rss_bytes")
        memory = f"{rss['median'] / 1024**2:.2f}" if rss else "unavailable"
        lines.append(
            f"| {case['name']} | {wall['median'] * 1000:.2f} | {wall['min'] * 1000:.2f}–{wall['max'] * 1000:.2f} | {memory} |"
        )
    if comparisons := report.get("comparison"):
        lines += ["", "| Case | Wall speedup (baseline/current) | RSS change % |", "| --- | ---: | ---: |"]
        for row in comparisons:
            memory_change = f"{row['rss_change_percent']:+.1f}" if "rss_change_percent" in row else "unavailable"
            lines.append(f"| {row['name']} | {row['wall_speedup']:.2f}x | {memory_change} |")
    lines += [
        "",
        "These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", help="command prefix, parsed with shlex; never executed through a shell")
    parser.add_argument("--label", default="rust-release")
    parser.add_argument("--profile", choices=PROFILES, default="standard")
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--case", action="append", dest="case_names", help="run only this named case; may be repeated")
    parser.add_argument("--baseline", type=Path, help="require equivalent results before reporting speedups")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.warmups < 0 or args.timeout <= 0:
        parser.error("repeats must be positive, warmups nonnegative, and timeout positive")
    if args.output.suffix != ".json":
        parser.error("--output must end in .json; a Markdown sidecar is written alongside it")
    command = (
        shlex.split(args.command)
        if args.command
        else [str(ROOT / "target/release" / ("agent-dump.exe" if os.name == "nt" else "agent-dump"))]
    )
    if not command:
        parser.error("command cannot be empty")
    executable = shutil.which(command[0])
    if executable is None:
        parser.error(f"executable not found: {command[0]}")
    command[0] = str(Path(executable).absolute())
    profile = PROFILES[args.profile]
    selected = cases(profile)
    if args.case_names:
        unknown = set(args.case_names) - {case.name for case in selected}
        if unknown:
            parser.error(f"unknown cases: {sorted(unknown)}")
        selected = [case for case in selected if case.name in args.case_names]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "fixture_version": FIXTURE_VERSION,
        "label": args.label,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_dirty": bool(git_output("status", "--porcelain")),
        "python_source_sha256": reference_source_digest(),
        "evaluator_sha256": files_digest(sorted((ROOT / "scripts").glob("benchmark_*.py"))),
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "command": [argument.replace(str(ROOT), "<REPO>") for argument in command],
        "executable_sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
        "executable_bytes": Path(command[0]).stat().st_size,
        "environment": environment_metadata(),
        "profile": args.profile,
        "profile_settings": asdict(profile),
        "repeats": args.repeats,
        "warmups": args.warmups,
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="agent-dump-benchmark-") as temporary:
        root = Path(temporary).resolve()
        environment = create_fixture(root, profile)
        environment.pop("PYTHONPATH", None)
        report["source_manifest"] = source_manifest(root)
        _, version = run_sample(
            command, Case("version", ("--version",), "version"), root, environment, timeout=args.timeout
        )
        report["cli_version"] = version.strip()
        for case in selected:
            print(f"Running {case.name} ...", flush=True)
            result = run_case(
                command,
                case,
                profile,
                root,
                environment,
                repeats=args.repeats,
                warmups=args.warmups,
                timeout=args.timeout,
            )
            report["cases"].append(result)
            print(f"  {result['summary']['wall_seconds']['median'] * 1000:.2f} ms median; validated", flush=True)
        require(source_manifest(root) == report["source_manifest"], "benchmark command modified Provider sources")
    if args.baseline:
        report["comparison"] = compare_reports(json.loads(args.baseline.read_text(encoding="utf-8")), report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")
    print(f"Saved {args.output} and {args.output.with_suffix('.md')}")


if __name__ == "__main__":
    main()
