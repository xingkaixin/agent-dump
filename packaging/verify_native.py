"""Exercise a built native binary against an isolated real session fixture."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from typing import Protocol

SESSION_ID = "019c213e-c251-73a3-af66-0ec9d7cb9e29"
USER_MARKER = "native smoke user marker"
ASSISTANT_MARKER = "native smoke assistant marker"


class CommandRunner(Protocol):
    def __call__(self, command: list[str], *, cwd: Path, env: Mapping[str, str]) -> str: ...


def write_codex_fixture(codex_home: Path) -> str:
    """Write the smallest Codex session that exercises discovery and parsing."""
    sessions_dir = codex_home / "sessions" / "2026" / "08"
    sessions_dir.mkdir(parents=True)
    session_file = sessions_dir / f"rollout-2026-08-18T10-04-47-{SESSION_ID}.jsonl"
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": SESSION_ID,
                "timestamp": "2026-08-18T10:04:47Z",
                "cwd": "/workspace/native-smoke",
                "cli_version": "1.2.3",
                "model_provider": "openai",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-08-18T10:05:00Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": USER_MARKER}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-08-18T10:05:10Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": ASSISTANT_MARKER}],
            },
        },
    ]
    session_file.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    (codex_home / "session_index.jsonl").write_text(
        json.dumps({"id": SESSION_ID, "thread_name": "Native smoke session"}) + "\n",
        encoding="utf-8",
    )
    return SESSION_ID


def build_isolated_environment(root: Path, codex_home: Path) -> dict[str, str]:
    """Point every provider discovery path at a disposable directory."""
    locations = {
        "HOME": root / "home",
        "USERPROFILE": root / "home",
        "XDG_DATA_HOME": root / "xdg-data",
        "XDG_CONFIG_HOME": root / "xdg-config",
        "XDG_CACHE_HOME": root / "xdg-cache",
        "APPDATA": root / "app-data",
        "LOCALAPPDATA": root / "local-app-data",
        "CLAUDE_CONFIG_DIR": root / "claude",
        "KIMI_SHARE_DIR": root / "kimi",
        "PI_HOME": root / "pi",
    }
    for path in locations.values():
        path.mkdir(parents=True, exist_ok=True)

    environment = dict(os.environ)
    environment.update({name: str(path) for name, path in locations.items()})
    environment.update(
        {
            "CODEX_HOME": str(codex_home),
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return environment


def run_command(command: list[str], *, cwd: Path, env: Mapping[str, str]) -> str:
    """Run one verification command and retain useful output on failure."""
    print(f"$ {shlex.join(command)}", flush=True)
    try:
        result = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"command timed out after 60 seconds: {shlex.join(command)}") from error

    if result.returncode != 0:
        details = f"{result.stdout}\n{result.stderr}".strip()[-8192:]
        raise RuntimeError(f"command failed with exit code {result.returncode}: {shlex.join(command)}\n{details}")
    return result.stdout


def validate_export(output_dir: Path, session_id: str) -> None:
    """Validate the shape and content of the JSON produced by the native CLI."""
    exports = sorted(output_dir.rglob("*.json"))
    if len(exports) != 1:
        raise RuntimeError(f"expected exactly one JSON export, found {[str(path) for path in exports]}")

    payload = json.loads(exports[0].read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("id") != session_id:
        raise RuntimeError("JSON export does not identify the fixture session")

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise RuntimeError("JSON export does not contain a message list")
    roles = {message.get("role") for message in messages if isinstance(message, dict)}
    if not {"user", "assistant"}.issubset(roles):
        raise RuntimeError(f"JSON export is missing expected message roles: {sorted(str(role) for role in roles)}")

    serialized = json.dumps(payload, ensure_ascii=False)
    missing_markers = [marker for marker in (USER_MARKER, ASSISTANT_MARKER) if marker not in serialized]
    if missing_markers:
        raise RuntimeError(f"JSON export is missing fixture content: {missing_markers}")


def verify_native(
    binary: Path,
    expected_version: str | None = None,
    *,
    runner: CommandRunner = run_command,
) -> None:
    """Run startup, URI rendering, and JSON export through a native binary."""
    resolved_binary = binary.expanduser().resolve()
    if not resolved_binary.is_file():
        raise RuntimeError(f"native binary does not exist: {resolved_binary}")

    with tempfile.TemporaryDirectory(prefix="agent-dump-native-") as workdir:
        root = Path(workdir)
        codex_home = root / "codex"
        session_id = write_codex_fixture(codex_home)
        environment = build_isolated_environment(root, codex_home)
        executable = str(resolved_binary)

        version_output = runner([executable, "--version"], cwd=root, env=environment).strip()
        if expected_version and expected_version not in version_output:
            raise RuntimeError(f"native CLI reports {version_output!r}, expected version {expected_version!r}")

        help_output = runner([executable, "--lang", "en", "--help"], cwd=root, env=environment)
        if "usage:" not in help_output:
            raise RuntimeError("native CLI help does not contain a usage line")

        uri = f"codex://{session_id}"
        rendered = runner([executable, uri, "--format", "print", "--lang", "en"], cwd=root, env=environment)
        missing_markers = [marker for marker in (USER_MARKER, ASSISTANT_MARKER) if marker not in rendered]
        if missing_markers:
            raise RuntimeError(f"native CLI print output is missing fixture content: {missing_markers}")

        output_dir = root / "exports"
        runner(
            [executable, uri, "--format", "json", "--output", str(output_dir), "--lang", "en"],
            cwd=root,
            env=environment,
        )
        validate_export(output_dir, session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-version", default=None)
    args = parser.parse_args()

    try:
        verify_native(args.binary, args.expected_version)
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    print("native CLI completed an isolated session workflow")


if __name__ == "__main__":
    main()
