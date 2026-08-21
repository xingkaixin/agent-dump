"""Append-only diagnostics logging for collect mode."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from agent_dump.config import LoggingConfig
from agent_dump.private_files import open_private_append

CollectLogErrorHandler = Callable[[Path, OSError], None]


@dataclass
class CollectLogger:
    """Write private JSONL diagnostics without interrupting collect work."""

    enabled: bool
    path: Path | None = None
    run_id: str | None = None
    on_write_error: CollectLogErrorHandler | None = None
    _write_failed: bool = field(default=False, init=False, repr=False)
    _write_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def log(self, event: str, **payload: Any) -> None:
        if not self.enabled or self.path is None:
            return

        error: OSError | None = None
        with self._write_lock:
            if self._write_failed:
                return
            try:
                record = {
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "event": event,
                    "run_id": self.run_id,
                    **payload,
                }
                with open_private_append(self.path) as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as exc:
                self._write_failed = True
                error = exc

        if error is not None and self.on_write_error is not None:
            try:
                self.on_write_error(self.path, error)
            except OSError:
                return


def create_collect_logger(
    config: LoggingConfig | None,
    *,
    on_write_error: CollectLogErrorHandler | None = None,
) -> CollectLogger:
    """Create a collect logger from config."""
    run_id = str(uuid4())
    if config is None or not config.enabled:
        return CollectLogger(enabled=False, run_id=run_id, on_write_error=on_write_error)
    return CollectLogger(
        enabled=True,
        path=config.path,
        run_id=run_id,
        on_write_error=on_write_error,
    )
