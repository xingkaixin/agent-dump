#!/usr/bin/env python3
import argparse
from collections.abc import Callable
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_dump.agents.codex import CodexAgent  # noqa: E402


def create_codex_fixture(root: Path, *, small_count: int, large_count: int, large_payload_bytes: int) -> list[Path]:
    files: list[Path] = []
    for index in range(small_count):
        file_path = root / f"small-{index:05d}.jsonl"
        _write_jsonl(
            file_path,
            [
                _codex_record(index=index, second=0, role="user", text="first"),
                _codex_record(index=index, second=1, role="user", text=f"small title {index}"),
                _codex_record(index=index, second=2, role="assistant", text="done"),
            ],
        )
        files.append(file_path)

    large_text = "x" * large_payload_bytes
    for index in range(large_count):
        session_index = small_count + index
        file_path = root / f"large-{index:05d}.jsonl"
        _write_jsonl(
            file_path,
            [
                _codex_record(index=session_index, second=0, role="user", text="first"),
                _codex_record(index=session_index, second=1, role="user", text=f"large title {index}"),
                _codex_model_record(index=session_index, second=2),
                _codex_record(index=session_index, second=3, role="assistant", text=large_text),
                _codex_record(index=session_index, second=4, role="assistant", text="done"),
            ],
        )
        files.append(file_path)

    return files


def _codex_record(*, index: int, second: int, role: str, text: str) -> dict[str, Any]:
    timestamp = f"2026-01-01T00:00:{second:02d}Z"
    return {
        "timestamp": timestamp,
        "payload": {
            "id": f"session-{index}",
            "timestamp": timestamp,
            "cwd": "/benchmark/agent-dump",
            "model_provider": "openai",
            "type": "message",
            "role": role,
            "content": [{"text": text}],
        },
    }


def _codex_model_record(*, index: int, second: int) -> dict[str, Any]:
    timestamp = f"2026-01-01T00:00:{second:02d}Z"
    return {
        "timestamp": timestamp,
        "payload": {
            "id": f"session-{index}",
            "timestamp": timestamp,
            "cwd": "/benchmark/agent-dump",
            "type": "function_call",
            "arguments": {"model": "gpt-5.4-mini"},
        },
    }


def _write_jsonl(file_path: Path, records: list[dict[str, Any]]) -> None:
    file_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def run_readlines_baseline(files: list[Path]) -> int:
    parsed = 0
    for file_path in files:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            continue
        json.loads(lines[0])
        for line in lines:
            json.loads(line)
        parsed += 1
    return parsed


def run_current_parser(files: list[Path]) -> int:
    agent = CodexAgent()
    agent.base_path = files[0].parent if files else None
    agent._titles_cache = {}
    return len(agent.get_sessions(days=3650))


def measure_seconds(fn: Callable[[list[Path]], int], files: list[Path], *, repeats: int) -> tuple[float, int]:
    best_elapsed = float("inf")
    parsed_count = 0
    for _ in range(repeats):
        start = time.perf_counter()
        parsed_count = fn(files)
        elapsed = time.perf_counter() - start
        best_elapsed = min(best_elapsed, elapsed)
    return best_elapsed, parsed_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Codex list-scan parsing.")
    parser.add_argument("--small", type=int, default=500, help="number of small JSONL files")
    parser.add_argument("--large", type=int, default=5, help="number of large JSONL files")
    parser.add_argument("--large-mb", type=int, default=4, help="payload size per large file")
    parser.add_argument("--repeats", type=int, default=3, help="repeat count; best run is reported")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="agent-dump-scan-") as temp_dir:
        root = Path(temp_dir)
        files = create_codex_fixture(
            root,
            small_count=args.small,
            large_count=args.large,
            large_payload_bytes=args.large_mb * 1024 * 1024,
        )
        total_bytes = sum(file_path.stat().st_size for file_path in files)
        baseline_seconds, baseline_count = measure_seconds(run_readlines_baseline, files, repeats=args.repeats)
        current_seconds, current_count = measure_seconds(run_current_parser, files, repeats=args.repeats)

    speedup = baseline_seconds / current_seconds if current_seconds > 0 else float("inf")
    print(f"files: {len(files)} ({args.small} small, {args.large} large)")
    print(f"bytes: {total_bytes:,}")
    print(f"readlines baseline: {baseline_seconds:.4f}s ({baseline_count} sessions)")
    print(f"bounded parser:     {current_seconds:.4f}s ({current_count} sessions)")
    print(f"speedup:            {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
