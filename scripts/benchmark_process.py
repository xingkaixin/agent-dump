"""Measure exactly one CLI invocation in a fresh collector process."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required")

    started = time.perf_counter()
    with subprocess.Popen(command, start_new_session=os.name != "nt") as process:  # noqa: S603
        timed_out = threading.Event()

        def terminate() -> None:
            if process.poll() is not None:
                return
            timed_out.set()
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)

        timer = threading.Timer(args.timeout, terminate)
        timer.start()
        try:
            returncode = process.wait()
        finally:
            timer.cancel()
            timer.join()
        if timed_out.is_set():
            raise SystemExit(f"benchmark command exceeded {args.timeout} seconds") from None
    elapsed = time.perf_counter() - started
    metrics = {"wall_seconds": elapsed, "exit_code": returncode}
    if sys.platform in {"darwin", "linux"}:
        import resource

        # A fresh collector has exactly one child; RUSAGE_CHILDREN is never reused across samples.
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        metrics.update(
            user_seconds=usage.ru_utime,
            system_seconds=usage.ru_stime,
            peak_rss_bytes=int(usage.ru_maxrss * (1024 if sys.platform == "linux" else 1)),
        )
    args.metrics.write_text(json.dumps(metrics), encoding="utf-8")


if __name__ == "__main__":
    main()
