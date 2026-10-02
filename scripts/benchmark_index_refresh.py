"""Compare SQLite index refreshes while retaining database and WAL change signals."""

import argparse
from contextlib import closing
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from benchmark_cases import Case, require
from benchmark_cli import ROOT, environment_metadata, run_sample, summarize
from benchmark_fixtures import Profile, create_fixture
from eval_rust_workflows import source_digest


def validate(output: str, expected: set[str]) -> None:
    payload = json.loads(output)
    require(payload["schema_version"] == 1 and payload["kind"] == "search", "unexpected search envelope")
    require(payload["status"] == "ok", "search reported incomplete results")
    require(not payload["failed_providers"] and not payload["failed_sessions"], "search reported failures")
    actual = [item["uri"] for item in payload["data"]]
    require(set(actual) == expected and len(actual) == len(expected), "search results differ from fixture")


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
    commands = {label: [str(getattr(args, label).resolve())] for label in ("baseline", "candidate")}
    profile = Profile(args.sessions, 8, 1024, 1024)
    catalog = json.loads((ROOT / "resources/locales/en.json").read_text(encoding="utf-8"))
    progress = (
        catalog["INDEX_UPDATE_PROGRESS"].format(agent="OpenCode", count=args.sessions) + "\n"
        if args.sessions >= 10
        else ""
    )
    report = {
        "environment": environment_metadata(),
        "profile": asdict(profile),
        "repeats": args.repeats,
        "warmups_per_binary": 1,
        "executables": {
            label: {"path": command[0], "sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()}
            for label, command in commands.items()
        },
        "cases": [],
    }
    for name in ["fresh-index", "warm-index", "metadata-refresh", "message-refresh"]:
        with tempfile.TemporaryDirectory(prefix="agent-dump-index-refresh-") as temporary:
            root = Path(temporary).resolve()
            environment = create_fixture(root, profile)
            gc.collect()
            database = root / "sources/opencode.db"
            index = root / "cache/agent-dump/search-index.db"
            seed = root / "seed.db"
            options = ("--query", "provider:opencode", "--days", "36500", "--json")
            with closing(sqlite3.connect(database)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                prepare = Case("prepare", ("--search", "payload", *options), "search")
                before_prepare = source_digest(root)
                _, output = run_sample(commands["baseline"], prepare, root, environment, timeout=120)
                validate(output, {f"opencode://ses_bench_{i:06d}" for i in range(args.sessions)})
                require(source_digest(root) == before_prepare, "index preparation modified Provider sources")
                require(not index.with_name(index.name + "-wal").exists(), "seed index still has a WAL")
                shutil.copyfile(index, seed)
                times = writer.execute("SELECT id, time_created, time_updated FROM session_v2 ORDER BY id").fetchall()
                main_database = database.read_bytes()
                keyword = "quartz"
                expected = {f"opencode://ses_bench_{i:06d}" for i in range(0, args.sessions, 10)}
                if name == "metadata-refresh":
                    writer.execute("UPDATE session_v2 SET cost = 1 WHERE id = 'ses_bench_000000'")
                elif name == "message-refresh":
                    keyword = "delta-wal"
                    expected = {"opencode://ses_bench_000000"}
                    writer.execute(
                        "UPDATE session_message SET data = ? WHERE id = 'ses_bench_000000_0'",
                        (json.dumps({"text": "delta-wal 新增正文"}),),
                    )
                writer.commit()
                require(database.read_bytes() == main_database, "fixture unexpectedly checkpointed its WAL")
                require(
                    writer.execute("SELECT id, time_created, time_updated FROM session_v2 ORDER BY id").fetchall()
                    == times,
                    "fixture changed session timestamps",
                )
                before = source_digest(root)
                case = Case(name, ("--search", keyword, *options), "search")
                samples: dict[str, list[dict]] = {"baseline": [], "candidate": []}
                reference = None
                for iteration in range(args.repeats + 1):
                    order = ("baseline", "candidate") if iteration % 2 == 0 else ("candidate", "baseline")
                    for label in order:
                        if name == "fresh-index":
                            index.unlink(missing_ok=True)
                        else:
                            shutil.copyfile(seed, index)
                        metrics, output = run_sample(commands[label], case, root, environment, timeout=120)
                        validate(output, expected)
                        raw = (root / "stdout.txt").read_bytes()
                        if reference is None:
                            reference = raw
                        require(raw == reference, f"{name}: stdout differs between binaries or repetitions")
                        diagnostics = (root / "stderr.txt").read_text(encoding="utf-8")
                        require(diagnostics == ("" if name == "warm-index" else progress), "unexpected diagnostics")
                        if iteration:
                            metrics["index_bytes"] = index.stat().st_size
                            samples[label].append(metrics)
                if reference is None:
                    raise ValueError("benchmark produced no output")
                require(source_digest(root) == before, "benchmark modified Provider sources")
                summary = {label: summarize(values) for label, values in samples.items()}
                report["cases"].append(
                    {
                        "name": name,
                        "args": case.args,
                        "source_sha256": before,
                        "stdout_sha256": hashlib.sha256(reference).hexdigest(),
                        "samples": samples,
                        "summary": summary,
                    }
                )
                print(
                    name,
                    {label: round(values["wall_seconds"]["median"] * 1000, 2) for label, values in summary.items()},
                    flush=True,
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
