"""The Rust wheel promises a standalone CLI, without an accidental Python runtime."""

import importlib
from pathlib import Path
import sys
import zipfile

import pytest


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "packaging"))
    return importlib.import_module("verify_wheel")


@pytest.mark.parametrize("extra", [None, "dependency", "python-module", "missing-binary", "wrong-version"])
def test_cli_only_wheel_contract(tmp_path, verifier, extra):
    wheel = tmp_path / "agent_dump.whl"
    metadata = "Name: agent-dump\nVersion: 1.2.3\n"
    if extra == "dependency":
        metadata += "Requires-Dist: questionary\n"
    binary = "agent-dump.exe" if sys.platform == "win32" else "agent-dump"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("agent_dump-1.2.3.dist-info/METADATA", metadata)
        if extra != "missing-binary":
            archive.writestr(f"agent_dump-1.2.3.data/scripts/{binary}", b"native executable")
        if extra == "python-module":
            archive.writestr("agent_dump/__init__.py", "")
    if extra:
        with pytest.raises(ValueError):
            verifier.validate_wheel(wheel, "9.9.9" if extra == "wrong-version" else "1.2.3")
    else:
        assert verifier.validate_wheel(wheel, "1.2.3") == "1.2.3"
