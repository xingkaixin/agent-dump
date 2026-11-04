"""Tests for GitHub release asset retry validation."""

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "packaging" / "verify_release_assets.py"
SPEC = importlib.util.spec_from_file_location("agent_dump_verify_release_assets", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
release_assets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_assets
SPEC.loader.exec_module(release_assets)


def test_verify_existing_assets_accepts_identical_and_missing_remote_assets(tmp_path):
    existing = tmp_path / "existing.bin"
    existing.write_bytes(b"same")
    missing = tmp_path / "missing.bin"
    missing.write_bytes(b"new")
    digest = "sha256:" + hashlib.sha256(b"same").hexdigest()

    verified = release_assets.verify_existing_assets(
        [existing, missing],
        {"existing.bin": digest},
    )

    assert verified == ("existing.bin",)


def test_verify_existing_assets_rejects_changed_content(tmp_path):
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"local")

    with pytest.raises(ValueError, match="different contents"):
        release_assets.verify_existing_assets([asset], {"asset.bin": "sha256:" + "0" * 64})
