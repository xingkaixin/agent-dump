"""Verify a CLI-only wheel through pip, uv tool install and uvx in disposable homes."""

import argparse
from collections.abc import Mapping
from email.parser import BytesParser
from pathlib import Path
import sys
import tempfile
import zipfile

from verify_native import build_isolated_environment, run_command, verify_command

REPO_ROOT = Path(__file__).resolve().parent.parent


def _find_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected exactly one wheel in {dist_dir}, found: {[w.name for w in wheels]}")
    return wheels[0]


def validate_wheel(wheel: Path, expected_version: str | None) -> str:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Wheel must contain exactly one distribution")
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        version = str(metadata["Version"])
        if metadata["Name"] != "agent-dump" or (expected_version and expected_version != version):
            raise ValueError("Wheel name/version does not match release metadata")
        if metadata.get_all("Requires-Dist"):
            raise ValueError("CLI-only wheel must not have Python runtime dependencies")
        binary_name = "agent-dump.exe" if sys.platform == "win32" else "agent-dump"
        executable = f"agent_dump-{version}.data/scripts/{binary_name}"
        if executable not in names or not archive.read(executable):
            raise ValueError("Wheel must contain the native CLI")
        if any(name != executable and not name.startswith(f"agent_dump-{version}.dist-info/") for name in names):
            raise ValueError("CLI-only wheel contains unexpected runtime files")
    return version


def verify_wheel(wheel: Path, expected_version: str | None = None, python: str = sys.executable) -> None:
    wheel = wheel.resolve()
    expected_version = validate_wheel(wheel, expected_version)
    with tempfile.TemporaryDirectory(prefix="agent-dump-wheel-") as directory:
        root = Path(directory)
        environment = build_isolated_environment(root, root / "codex")
        environment.pop("PYTHONPATH", None)
        environment.update(
            {
                "UV_TOOL_DIR": str(root / "tools"),
                "UV_TOOL_BIN_DIR": str(root / "tool-bin"),
                "UV_CACHE_DIR": str(root / "cache"),
            }
        )

        def run(command: list[str]) -> str:
            return run_command(command, cwd=root, env=environment)

        venv = root / "venv"
        run(["uv", "venv", "--seed", "--python", python, str(venv)])
        scripts = venv / ("Scripts" if sys.platform == "win32" else "bin")
        interpreter = str(scripts / ("python.exe" if sys.platform == "win32" else "python"))
        run([interpreter, "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)])
        run([interpreter, "-I", "-c", "import importlib.util; assert importlib.util.find_spec('agent_dump') is None"])
        binary_name = "agent-dump.exe" if sys.platform == "win32" else "agent-dump"
        verify_command([str(scripts / binary_name)], expected_version)
        run(["uv", "tool", "install", "--no-index", "--python", python, str(wheel)])
        verify_command([str(root / "tool-bin" / binary_name)], expected_version)

        def tool_runner(command: list[str], *, cwd: Path, env: Mapping[str, str]) -> str:
            merged = dict(env)
            merged.update({key: value for key, value in environment.items() if key.startswith("UV_")})
            merged.pop("PYTHONPATH", None)
            return run_command(command, cwd=cwd, env=merged)

        verify_command(
            ["uv", "tool", "run", "--isolated", "--no-index", "--python", python, "--from", str(wheel), "agent-dump"],
            expected_version,
            runner=tool_runner,
        )
    print(f"Verified pip, uv tool install and uvx: {wheel.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--expected-version")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    verify_wheel(_find_wheel(args.dist_dir), args.expected_version, args.python)


if __name__ == "__main__":
    main()
