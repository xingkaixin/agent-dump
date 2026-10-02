"""Compare release reader redraw harnesses with identical complete terminal buffers."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile

from benchmark_cases import require
from benchmark_cli import environment_metadata
from benchmark_fixtures import isolated_environment

CASES = {"small": (128, 1), "many-sessions": (128, 1000), "large-message": (8 * 1024 * 1024, 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    binaries = {label: getattr(args, label).resolve() for label in ("baseline", "candidate")}
    samples: dict[str, dict[str, list[float]]] = {name: {label: [] for label in binaries} for name in CASES}
    reference = {}
    with tempfile.TemporaryDirectory(prefix="agent-dump-reader-redraw-") as temporary:
        root = Path(temporary).resolve()
        environment = isolated_environment(root)
        for iteration in range(args.repeats + 1):
            order = ("baseline", "candidate") if iteration % 2 == 0 else ("candidate", "baseline")
            for label in order:
                result = subprocess.run(  # noqa: S603
                    [
                        str(binaries[label]),
                        "--ignored",
                        "--exact",
                        "terminal::reader::tests::benchmark_reader_redraw",
                        "--nocapture",
                    ],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=120,
                    check=False,
                )
                require(result.returncode == 0 and not result.stderr, result.stdout + result.stderr)
                records = [
                    json.loads(line.split("REDRAW_BENCH ", 1)[1])
                    for line in result.stdout.splitlines()
                    if "REDRAW_BENCH " in line
                ]
                require(len(records) == len(CASES), "missing redraw measurements")
                require({record["name"] for record in records} == set(CASES), "unexpected redraw cases")
                for record in records:
                    name = record["name"]
                    require((record["chars"], record["rows"]) == CASES[name], "unexpected redraw fixture")
                    require(record["iterations"] == 200, "unexpected draw count")
                    elapsed = record.pop("elapsed_seconds")
                    require(math.isfinite(elapsed) and elapsed > 0, "invalid draw duration")
                    if name not in reference:
                        reference[name] = record
                    require(record == reference[name], "terminal text, styles, or fixture differ between samples")
                    if iteration:
                        samples[name][label].append(elapsed / record["iterations"])
            print(f"Pair {iteration}/{args.repeats} complete", flush=True)
    report = {
        "environment": environment_metadata(),
        "repeats": args.repeats,
        "warmups_per_binary": 1,
        "executables": {
            label: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for label, path in binaries.items()
        },
        "cases": [],
    }
    for name, values in samples.items():
        summary = {
            label: {
                "median": statistics.median(times),
                "min": min(times),
                "max": max(times),
                "stdev": statistics.stdev(times) if len(times) > 1 else 0,
            }
            for label, times in values.items()
        }
        report["cases"].append({**reference[name], "draw_seconds_samples": values, "draw_seconds_summary": summary})
        print(name, {label: round(times["median"] * 1000, 4) for label, times in summary.items()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
