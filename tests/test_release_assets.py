"""Tests for GitHub release asset retry validation."""

from email.message import Message
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest import mock
from urllib.error import HTTPError

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "packaging" / "verify_release_assets.py"
SPEC = importlib.util.spec_from_file_location("agent_dump_verify_release_assets", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
release_assets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_assets
SPEC.loader.exec_module(release_assets)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self._body

    def __exit__(self, *_args) -> None:
        return None


def test_fetch_release_asset_digests_reads_names_and_digests():
    payload = {"assets": [{"name": "agent-dump", "digest": "sha256:abc"}]}
    with mock.patch.object(release_assets, "urlopen", return_value=FakeResponse(payload)) as open_url:
        digests = release_assets.fetch_release_asset_digests("owner/repo", "v1.2.3", "token")

    assert digests == {"agent-dump": "sha256:abc"}
    request = open_url.call_args.args[0]
    assert request.full_url.endswith("/repos/owner/repo/releases/tags/v1.2.3")
    assert request.headers["Authorization"] == "Bearer token"


def test_fetch_release_asset_digests_treats_missing_release_as_empty():
    error = HTTPError("https://api.github.test", 404, "missing", Message(), None)
    with mock.patch.object(release_assets, "urlopen", side_effect=error):
        assert release_assets.fetch_release_asset_digests("owner/repo", "v1.2.3", "token") == {}


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


def test_verify_existing_assets_fails_when_remote_digest_is_unavailable(tmp_path):
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"local")

    with pytest.raises(ValueError, match="did not provide a digest"):
        release_assets.verify_existing_assets([asset], {"asset.bin": None})
