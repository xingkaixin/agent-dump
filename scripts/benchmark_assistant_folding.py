"""Compare complete exports of long synthetic Codex and Claude assistant streams."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from benchmark_cases import Case, require
from benchmark_cli import environment_metadata, reset_outputs, run_sample, summarize
from benchmark_fixtures import EPOCH, codex_id, isolated_environment, source_manifest


def create_streams(root: Path, count: int) -> dict[str, str]:
    environment = isolated_environment(root)
    identity = codex_id(0)
    stamp = EPOCH.isoformat()
    for provider in ("codex", "claude"):
        directory = root / "sources" / provider / ("sessions/2026/01/15" if provider == "codex" else "projects/project")
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"{identity}.jsonl").open("w", encoding="utf-8") as stream:
            if provider == "codex":
                header = {"type": "session_meta", "payload": {"id": identity, "timestamp": stamp, "cwd": "/benchmark"}}
                stream.write(json.dumps(header) + "\n")
            for index in range(count + 1):
                role = "user" if index == 0 else "assistant"
                body = "Start" if index == 0 else f"fragment-{index:06d} 中文"
                if provider == "codex":
                    record = {
                        "type": "response_item",
                        "timestamp": stamp,
                        "payload": {
                            "type": "message",
                            "role": role,
                            "content": [{"type": "input_text" if index == 0 else "output_text", "text": body}],
                        },
                    }
                else:
                    record = {
                        "type": role,
                        "uuid": f"event-{index}",
                        "timestamp": stamp,
                        "cwd": "/benchmark",
                        "version": "1.0",
                        "message": {"role": role, "content": [{"type": "text", "text": body}]},
                    }
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return environment


def exported_bytes(root: Path, count: int) -> bytes:
    files = list((root / "exports").rglob("*.json"))
    require(len(files) == 1, "expected one JSON export")
    exported = files[0].read_bytes()
    payload = json.loads(exported)
    require(payload["id"] == codex_id(0), "unexpected session identity")
    messages = payload["messages"]
    require([message["role"] for message in messages] == ["user", "assistant"], "incorrect folding boundaries")
    require(messages[0]["parts"][0]["text"] == "Start", "missing user text")
    parts = messages[1]["parts"]
    require(len(parts) == count, "missing or duplicated assistant fragments")
    require(
        all(
            part["type"] == "text" and part["text"] == f"fragment-{index:06d} 中文"
            for index, part in enumerate(parts, 1)
        ),
        "assistant fragments changed order or content",
    )
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[16000, 32000])
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 1 or any(size < 1 for size in args.sizes):
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
    for count in args.sizes:
        with tempfile.TemporaryDirectory(prefix="agent-dump-folding-") as temporary:
            root = Path(temporary).resolve()
            environment = create_streams(root, count)
            before = source_manifest(root)
            results = []
            for provider in ("codex", "claude"):
                case = Case(
                    provider, (f"{provider}://{codex_id(0)}", "--format", "json", "--output", "exports"), "export"
                )
                samples: dict[str, list[dict]] = {"baseline": [], "candidate": []}
                reference: tuple[str, bytes] | None = None
                for iteration in range(args.repeats + 1):
                    order = ("baseline", "candidate") if iteration % 2 == 0 else ("candidate", "baseline")
                    for label in order:
                        reset_outputs(root, reset_index=True)
                        metrics, output = run_sample(commands[label], case, root, environment, timeout=120)
                        exported = exported_bytes(root, count)
                        require(metrics["stderr_bytes"] == 0, "unexpected export diagnostics")
                        if reference is None:
                            reference = (output, exported)
                        require((output, exported) == reference, "stdout or complete export differs between samples")
                        if iteration:
                            samples[label].append(metrics)
                if reference is None:
                    raise ValueError("benchmark produced no export")
                summary = {label: summarize(values) for label, values in samples.items()}
                results.append(
                    {
                        "provider": provider,
                        "args": case.args,
                        "stdout_sha256": hashlib.sha256(reference[0].encode()).hexdigest(),
                        "export_sha256": hashlib.sha256(reference[1]).hexdigest(),
                        "export_bytes": len(reference[1]),
                        "samples": samples,
                        "summary": summary,
                    }
                )
                print(
                    count,
                    provider,
                    {label: round(values["wall_seconds"]["median"] * 1000, 2) for label, values in summary.items()},
                    flush=True,
                )
            require(source_manifest(root) == before, "benchmark modified Provider sources")
            report["fixtures"].append({"fragments": count, "source_manifest": before, "cases": results})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
