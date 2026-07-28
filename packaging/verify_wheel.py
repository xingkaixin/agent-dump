"""Install a built wheel into a clean environment and run its console entrypoint.

`uv build` 只保证能打出包，不保证装上去之后 `agent-dump` 真的能起来：console
entrypoint 拼错、缺运行期依赖、包数据没进 wheel，这些都要到用户安装时才暴露。
PyPI 的版本不可覆盖，所以这一步必须发生在第一条 publish 之前。

本地 `just` 与 release workflow 共用这个脚本，避免 workflow 里再抄一份实现。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent


def _find_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise SystemExit(f"no wheel found in {dist_dir}")
    if len(wheels) > 1:
        raise SystemExit(f"expected exactly one wheel in {dist_dir}, found: {[w.name for w in wheels]}")
    return wheels[0]


def _run(command: list[str]) -> str:
    print(f"$ {' '.join(command)}", flush=True)
    # 命令全部由本脚本构造：uv 本身，以及刚装进临时 venv 的 console entrypoint
    result = subprocess.run(command, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"command failed with exit code {result.returncode}: {' '.join(command)}")
    return result.stdout


def verify_wheel(wheel: Path, expected_version: str | None = None) -> None:
    """Install the wheel into a throwaway venv and run the CLI from it."""
    with tempfile.TemporaryDirectory() as workdir:
        venv = Path(workdir) / "venv"
        # 临时目录里的新 venv：装的必须是 wheel 自己声明的东西，不能借到仓库开发环境
        _run(["uv", "venv", str(venv)])
        _run(["uv", "pip", "install", "--python", str(venv), str(wheel)])

        binary = (
            venv
            / ("Scripts" if sys.platform == "win32" else "bin")
            / ("agent-dump.exe" if sys.platform == "win32" else "agent-dump")
        )
        if not binary.exists():
            raise SystemExit(f"wheel does not install a console entrypoint at {binary}")

        version_output = _run([str(binary), "--version"]).strip()
        print(f"installed CLI reports: {version_output}")
        if expected_version and expected_version not in version_output:
            raise SystemExit(f"installed CLI reports {version_output!r}, expected version {expected_version!r}")

        _run([str(binary), "--help"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--expected-version", default=None)
    args = parser.parse_args()

    wheel = _find_wheel(args.dist_dir)
    print(f"verifying {wheel.name}")
    verify_wheel(wheel, args.expected_version)
    print("wheel installs and runs from a clean environment")


if __name__ == "__main__":
    main()
