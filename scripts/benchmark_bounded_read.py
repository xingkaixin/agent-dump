"""Compare bounded reads using isolated large messages and identical cursors."""

import argparse
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import tempfile

from benchmark_cases import Case, require
from benchmark_cli import environment_metadata, run_sample, summarize
from benchmark_fixtures import Profile, codex_id, create_fixture, session_messages, source_manifest


def validate(output: str, uri: str, body: str, offset: int) -> dict:
    payload = json.loads(output)
    require(payload["schema_version"] == 1 and payload["kind"] == "read", "unexpected read envelope")
    require(payload["status"] == "ok" and payload["has_more"], "read reported incomplete or exhausted input")
    data = payload["data"]
    require(data["uri"] == uri and data["total_messages"] == 2, "unexpected session")
    require(len(data["messages"]) == 1 and data["next_cursor"], "unexpected page boundaries")
    fragment = data["messages"][0]
    require(fragment["position"] == 2 and fragment["role"] == "assistant", "unexpected message")
    require(fragment["text"] == body[offset : offset + 12000], "page text differs from fixture")
    require(fragment["start"] == offset and fragment["end"] == offset + 12000, "incorrect continuation offset")
    require(fragment["total_chars"] == len(body) and fragment["truncated"], "incorrect message length")
    require(fragment["locator"] == f"{data['revision']}:2", "incorrect message locator")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[8, 32], help="large message sizes in Mi characters")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if any(size < 1 for size in args.sizes) or args.repeats < 1:
        parser.error("sizes and repeats must be positive")
    commands = {label: [str(getattr(args, label).resolve())] for label in ("baseline", "candidate")}
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
    for size in args.sizes:
        profile = Profile(1, 2, 128, size * 1024 * 1024)
        with tempfile.TemporaryDirectory(prefix="agent-dump-bounded-read-") as temporary:
            root = Path(temporary).resolve()
            environment = create_fixture(root, profile)
            gc.collect()
            before = source_manifest(root)
            uri = f"codex://{codex_id(1)}"
            body = session_messages(profile, 1)[1][1].strip()
            first = Case("first", (uri, "--read", "--json"), "read")
            _, output = run_sample(commands["baseline"], first, root, environment, timeout=60)
            cursor = validate(output, uri, body, 0)["next_cursor"]
            workloads = [
                (first, 0),
                (Case("continue", (uri, "--read", "--cursor", cursor, "--json"), "read"), 12000),
                (Case("details", (uri, "--read", "--details", "--json"), "read"), 0),
            ]
            results = []
            for case, offset in workloads:
                samples: dict[str, list[dict]] = {"baseline": [], "candidate": []}
                reference = None
                for iteration in range(args.repeats + 1):
                    order = ("baseline", "candidate") if iteration % 2 == 0 else ("candidate", "baseline")
                    for label in order:
                        metrics, output = run_sample(commands[label], case, root, environment, timeout=60)
                        validate(output, uri, body, offset)
                        if reference is None:
                            reference = output
                        require(output == reference, f"{case.name}: stdout differs between binaries or repetitions")
                        require(metrics["stderr_bytes"] == 0, f"{case.name}: unexpected diagnostics")
                        if iteration:
                            samples[label].append(metrics)
                if reference is None:
                    raise ValueError("benchmark produced no output")
                summary = {label: summarize(values) for label, values in samples.items()}
                results.append(
                    {
                        "name": case.name,
                        "args": case.args,
                        "stdout_sha256": hashlib.sha256(reference.encode()).hexdigest(),
                        "samples": samples,
                        "summary": summary,
                    }
                )
                print(
                    size,
                    case.name,
                    {
                        label: {
                            "ms": round(values["wall_seconds"]["median"] * 1000, 2),
                            "rss_mib": round(values["peak_rss_bytes"]["median"] / 1024**2, 2)
                            if "peak_rss_bytes" in values
                            else None,
                        }
                        for label, values in summary.items()
                    },
                    flush=True,
                )
            require(source_manifest(root) == before, "benchmark modified Provider sources")
            report["fixtures"].append({"profile": asdict(profile), "source_manifest": before, "cases": results})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
