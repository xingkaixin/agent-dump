"""Install and locate the immutable Python CLI used only by differential evaluation."""

import argparse
from functools import cache
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv-reference"
PYTHON = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SOURCE_SHA256 = "a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237"


def command() -> list[str]:
    if not PYTHON.is_file():
        raise RuntimeError("Python reference missing; run `just reference` before differential evaluation")
    return [str(PYTHON), "-m", "agent_dump"]


@cache
def source_digest() -> str | None:
    if not PYTHON.is_file():
        return None
    source = Path(
        subprocess.check_output(  # noqa: S603
            [str(PYTHON), "-I", "-c", "import agent_dump; print(agent_dump.__path__[0])"], text=True
        ).strip()
    )
    digest = hashlib.sha256()
    # Preserve the historical path prefix used in P0–P6 source fingerprints.
    for path in sorted(source.rglob("*.py")):
        digest.update((Path("src/agent_dump") / path.relative_to(source)).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def install() -> None:
    if not PYTHON.is_file():
        subprocess.run(["uv", "venv", "--python", sys.executable, str(ENVIRONMENT)], check=True)  # noqa: S603,S607
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "uv",
            "pip",
            "sync",
            "--compile-bytecode",
            "--python",
            str(PYTHON),
            "--require-hashes",
            "--only-binary",
            ":all:",
            str(ROOT / "tests/reference/requirements.txt"),
        ],
        check=True,
    )
    source_digest.cache_clear()
    if source_digest() != SOURCE_SHA256:
        raise RuntimeError("Installed Python reference differs from the accepted v0.15.9 source")
    print(f"Verified Python v0.15.9 reference: {SOURCE_SHA256}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    if parser.parse_args().install:
        install()
    else:
        print(PYTHON)
