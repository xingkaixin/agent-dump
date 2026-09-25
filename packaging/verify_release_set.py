"""Reject incomplete release sets or npm executables differing from their wheels."""

import argparse
import json
from pathlib import Path
import zipfile

from build_release import ROOT, version


def verify_release_set(dist: Path, npm: Path) -> None:
    expected_version = version()
    targets = json.loads((ROOT / "npm/packages/cli/lib/native-targets.json").read_text(encoding="utf-8"))
    wheels = set(dist.glob("*.whl"))
    if len(wheels) != len(targets):
        raise ValueError(f"Expected {len(targets)} wheels, found {len(wheels)}")
    for target in targets:
        matching = [wheel for wheel in wheels if target["wheelPlatform"] in wheel.name]
        if len(matching) != 1:
            raise ValueError(f"Missing or duplicate wheel for {target['target']}")
        wheel = matching[0]
        with zipfile.ZipFile(wheel) as archive:
            binary = archive.read(f"agent_dump-{expected_version}.data/scripts/{target['executableName']}")
        staged = npm / "packages" / target["packageName"].split("/")[1] / "bin" / target["executableName"]
        if staged.read_bytes() != binary:
            raise ValueError(f"npm and wheel contain different executables for {target['target']}")
        wheels.remove(wheel)
    if not (dist / f"agent_dump-{expected_version}.tar.gz").is_file():
        raise ValueError("Source distribution missing")
    print("Complete wheel/native release set has identical executables")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--npm", type=Path, default=ROOT / "npm")
    args = parser.parse_args()
    verify_release_set(args.dist, args.npm)


if __name__ == "__main__":
    main()
