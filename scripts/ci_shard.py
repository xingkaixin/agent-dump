"""Run a complete CLI test shard balanced by recorded platform timings."""

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def partition(files: list[str], timings: dict[str, float], count: int, overhead: float) -> list[list[str]]:
    if not 1 <= count <= len(files):
        raise ValueError("Shard count must be between one and the number of test files")
    known = [timings[name] for name in files if name in timings]
    fallback = statistics.mean(known) if known else 1.0
    weights = {name: timings.get(name, fallback) for name in files}
    shards: list[list[str]] = [[] for _ in range(count)]
    loads = [overhead, *([0.0] * (count - 1))]
    for name in sorted(files, key=lambda name: (-weights[name], name)):
        # An empty pytest selection would run the entire suite instead.
        index = min(range(count), key=lambda index: (bool(shards[index]), loads[index], index))
        shards[index].append(name)
        loads[index] += weights[name]
    return [sorted(shard) for shard in shards]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.shard < args.count:
        parser.error("--shard must be in the range [0, --count)")
    baseline = json.loads((ROOT / ".github/cli-test-timings.json").read_text(encoding="utf-8"))[sys.platform]
    files = [path.name for path in (ROOT / "tests/cli").glob("test_*.py")]
    selected = partition(files, baseline["files"], args.count, baseline["shard_zero_overhead"])[args.shard]
    print(f"Shard {args.shard}/{args.count}: {', '.join(selected)}", flush=True)
    if args.dry_run:
        return 0
    return subprocess.call(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--maxfail=10",
            "--durations=30",
            "--junitxml=dist/ci/parity.xml",
            *(f"tests/cli/{name}" for name in selected),
        ],
        cwd=ROOT,
    )


if __name__ == "__main__":
    sys.exit(main())
