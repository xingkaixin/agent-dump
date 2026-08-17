"""Tests for the native release smoke verifier."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "packaging" / "verify_native.py"
SPEC = importlib.util.spec_from_file_location("agent_dump_verify_native", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
native_verification = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native_verification
SPEC.loader.exec_module(native_verification)


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
        self.commands.append(command)
        assert all(
            Path(env[name]).is_relative_to(cwd)
            for name in (
                "HOME",
                "USERPROFILE",
                "XDG_DATA_HOME",
                "XDG_CONFIG_HOME",
                "XDG_CACHE_HOME",
                "APPDATA",
                "LOCALAPPDATA",
                "CLAUDE_CONFIG_DIR",
                "KIMI_SHARE_DIR",
                "PI_HOME",
                "CODEX_HOME",
            )
        )
        fixture = next(Path(env["CODEX_HOME"]).joinpath("sessions").rglob("*.jsonl"))
        fixture_text = fixture.read_text(encoding="utf-8")
        assert native_verification.USER_MARKER in fixture_text
        assert native_verification.ASSISTANT_MARKER in fixture_text

        if "--version" in command:
            return "agent-dump 1.2.3\n"
        if "--help" in command:
            return "usage: agent-dump [options]\n"

        output_format = command[command.index("--format") + 1]
        if output_format == "print":
            return f"{native_verification.USER_MARKER}\n{native_verification.ASSISTANT_MARKER}\n"

        output_dir = Path(command[command.index("--output") + 1]) / "codex"
        output_dir.mkdir(parents=True)
        (output_dir / "session.json").write_text(
            json.dumps(
                {
                    "id": native_verification.SESSION_ID,
                    "messages": [
                        {"role": "user", "parts": [{"text": native_verification.USER_MARKER}]},
                        {"role": "assistant", "parts": [{"text": native_verification.ASSISTANT_MARKER}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return "saved\n"


def test_verify_native_exercises_a_real_session_workflow(tmp_path):
    binary = tmp_path / "agent-dump"
    binary.touch()
    runner = FakeRunner()

    native_verification.verify_native(binary, "1.2.3", runner=runner)

    assert len(runner.commands) == 4
    assert [command[1:] for command in runner.commands[:2]] == [["--version"], ["--lang", "en", "--help"]]
    assert runner.commands[2][2:4] == ["--format", "print"]
    assert runner.commands[3][2:4] == ["--format", "json"]


def test_run_command_preserves_failure_output(tmp_path):
    with pytest.raises(RuntimeError, match="exit code 7") as error:
        native_verification.run_command(
            [sys.executable, "-c", "import sys; print('native smoke failed'); sys.exit(7)"],
            cwd=tmp_path,
            env={},
        )

    assert "native smoke failed" in str(error.value)
