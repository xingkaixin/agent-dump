"""Compare fixed read batch sizes using isolated JSONL and SQLite workloads."""

import argparse
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from benchmark_cases import Case, require
from benchmark_cli import environment_metadata, reset_outputs, run_sample, summarize
from benchmark_fixtures import (
    Profile,
    codex_id,
    isolated_environment,
    session_messages,
    source_manifest,
    write_codex,
    write_opencode,
)

PROFILES = {
    "smoke": Profile(4, 4, 128, 1024),
    "compact": Profile(256, 8, 256, 65536),
    "large": Profile(512, 20, 2048, 1048576),
}
BATCHES = (4, 8, 16, 32)


def index_digest(root: Path, provider: str, profile: Profile) -> str:
    count = profile.sessions_per_provider + (provider == "codex")
    expected = {
        codex_id(index) if provider == "codex" else f"ses_bench_{index:06d}": "\n\n".join(
            body.strip() for _, body in session_messages(profile, index)
        )
        for index in range(count)
    }
    database = root / "cache/agent-dump/search-index.db"
    require(database.is_file(), "index was not created")
    digest = hashlib.sha256()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        for table in ("sessions_fts_trigram", "sessions_fts"):
            rows = connection.execute(
                f"SELECT agent_name, session_id, title, content FROM {table} ORDER BY agent_name, session_id"  # noqa: S608
            ).fetchall()
            require(len(rows) == count and {row[1] for row in rows} == set(expected), "incorrect indexed sessions")
            require(all(row[0] == provider for row in rows), "unexpected indexed Provider")
            if table == "sessions_fts_trigram":
                require(all(row[3] == expected[row[1]] for row in rows), "indexed text differs from complete fixture")
            digest.update(json.dumps(rows, ensure_ascii=False).encode())
    return digest.hexdigest()


def workloads(provider: str) -> list[Case]:
    scope = ("--query", f"provider:{provider}")
    return [
        Case("cold-index", ("--reindex", "--days", "36500", *scope), "index"),
        Case(
            "collect-dry-run",
            ("--collect", "--dry-run", "--since", "20260115", "--until", "20260116", "--save", "report.md", *scope),
            "collect",
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for batch in BATCHES:
        parser.add_argument(f"--batch-{batch}", type=Path, required=True)
    parser.add_argument("--profiles", choices=PROFILES, nargs="+", default=["compact", "large"])
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    commands = {str(batch): [str(getattr(args, f"batch_{batch}").resolve())] for batch in BATCHES}
    report = {
        "environment": environment_metadata(),
        "repeats": args.repeats,
        "warmups_per_binary": 1,
        "executables": {
            label: {"path": command[0], "sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()}
            for label, command in commands.items()
        },
        "fixtures": [],
    }
    for name in args.profiles:
        profile = PROFILES[name]
        for provider in ("codex", "opencode"):
            with tempfile.TemporaryDirectory(prefix="agent-dump-read-batches-") as temporary:
                root = Path(temporary).resolve()
                environment = isolated_environment(root)
                (write_codex if provider == "codex" else write_opencode)(root, profile)
                before = source_manifest(root)
                count = profile.sessions_per_provider + (provider == "codex")
                results = []
                for case in workloads(provider):
                    samples: dict[str, list[dict]] = {label: [] for label in commands}
                    reference: tuple[str, str, str | None] | None = None
                    labels = list(commands)
                    for iteration in range(args.repeats + 1):
                        shift = iteration % len(labels)
                        for label in labels[shift:] + labels[:shift]:
                            reset_outputs(root, reset_index=True)
                            metrics, output = run_sample(commands[label], case, root, environment, timeout=180)
                            diagnostics = (root / "stderr.txt").read_text(encoding="utf-8")
                            indexed = None
                            if case.check == "index":
                                require(f"Total indexed: {count} sessions." in output, "incomplete indexing")
                                indexed = index_digest(root, provider, profile)
                            else:
                                require(f"Sessions: {count}\n" in output, "incorrect collect session count")
                                require(
                                    re.search(r"Chunks: [1-9][0-9]*", output) is not None, "collect produced no chunks"
                                )
                                require(not (root / "report.md").exists(), "dry-run wrote a report")
                            checked = (output, diagnostics, indexed)
                            if reference is None:
                                reference = checked
                            require(
                                checked == reference, "stdout, diagnostics, or indexed content changed across samples"
                            )
                            if iteration:
                                samples[label].append(metrics)
                    if reference is None:
                        raise ValueError("benchmark produced no output")
                    summary = {label: summarize(values) for label, values in samples.items()}
                    results.append(
                        {
                            "name": case.name,
                            "args": case.args,
                            "stdout_sha256": hashlib.sha256(reference[0].encode()).hexdigest(),
                            "stderr_sha256": hashlib.sha256(reference[1].encode()).hexdigest(),
                            "index_sha256": reference[2],
                            "samples": samples,
                            "summary": summary,
                        }
                    )
                    print(
                        name,
                        provider,
                        case.name,
                        {label: round(values["wall_seconds"]["median"] * 1000, 2) for label, values in summary.items()},
                        flush=True,
                    )
                require(source_manifest(root) == before, "benchmark modified Provider sources")
                report["fixtures"].append(
                    {
                        "name": name,
                        "provider": provider,
                        "profile": asdict(profile),
                        "sessions": count,
                        "source_manifest": before,
                        "cases": results,
                    }
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
