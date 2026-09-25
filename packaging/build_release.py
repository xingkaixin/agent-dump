"""Build the CLI-only wheel and stage its identical executable for npm."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def version() -> str:
    return tomllib.loads((ROOT / "rust" / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]


def build(output: Path) -> None:
    targets = json.loads((ROOT / "npm/packages/cli/lib/native-targets.json").read_text(encoding="utf-8"))
    architecture = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    target = next((t for t in targets if t["platform"] == sys.platform and t["arch"] == architecture), None)
    if target is None:
        raise ValueError(f"No release target for {sys.platform}/{architecture}")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if list(output.glob("*.whl")) or list(output.glob("*.tar.gz")):
        raise ValueError(f"Release output already contains distributions: {output}")
    command = [
        "uv",
        "build",
        "..",
        "--no-sources",
        "--build-constraint",
        "../packaging/build-constraints.txt",
        "--require-hashes",
        "--out-dir",
        str(output),
    ]
    if sys.platform == "linux":
        command += ["--config-setting", "build-args=--zig --compatibility manylinux_2_17 --auditwheel check"]
    environment = dict(os.environ)
    environment["CARGO_TARGET_DIR"] = str(ROOT / "rust" / "target")
    subprocess.run(command, cwd=ROOT / "rust", env=environment, check=True)  # noqa: S603
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1 or target["wheelPlatform"] not in wheels[0].name:
        raise ValueError(f"Unexpected wheel for {target['target']}: {wheels}")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        executable = f"agent_dump-{version()}.data/scripts/{target['executableName']}"
        payload = archive.read(executable)
    native = output / "native" / target["target"] / target["executableName"]
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_bytes(payload)
    native.chmod(0o755)
    report = {"target": target, "version": version(), "artifacts": []}
    for artifact in [wheel, *output.glob("*.tar.gz"), native]:
        report["artifacts"].append(
            {
                "file": artifact.relative_to(output).as_posix(),
                "bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        )
    (output / "artifact-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print(version())
    else:
        build(args.output)


if __name__ == "__main__":
    main()
