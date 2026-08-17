"""Verify existing GitHub release assets before an idempotent upload."""

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as asset:
        for chunk in iter(lambda: asset.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def fetch_release_asset_digests(repository: str, tag: str, token: str) -> dict[str, str | None]:
    owner, separator, name = repository.partition("/")
    if not separator or not owner or not name or "/" in name:
        raise ValueError(f"invalid GitHub repository: {repository}")
    url = (
        f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
        f"/releases/tags/{quote(tag, safe='')}"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS GitHub API origin
            payload: Any = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return {}
        raise

    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        raise ValueError("GitHub release response has no asset list")
    digests: dict[str, str | None] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise ValueError("GitHub release response contains an invalid asset")
        asset_name = asset["name"]
        if asset_name in digests:
            raise ValueError(f"GitHub release contains duplicate asset name: {asset_name}")
        digest = asset.get("digest")
        digests[asset_name] = digest if isinstance(digest, str) else None
    return digests


def verify_existing_assets(paths: Sequence[Path], remote_digests: Mapping[str, str | None]) -> tuple[str, ...]:
    local_paths: dict[str, Path] = {}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.name in local_paths:
            raise ValueError(f"duplicate local release asset name: {path.name}")
        local_paths[path.name] = path

    verified: list[str] = []
    for name, path in local_paths.items():
        if name not in remote_digests:
            continue
        remote_digest = remote_digests[name]
        if remote_digest is None:
            raise ValueError(f"GitHub did not provide a digest for existing asset: {name}")
        local_digest = sha256_digest(path)
        if not hmac.compare_digest(local_digest, remote_digest):
            raise ValueError(f"GitHub release asset already exists with different contents: {name}")
        verified.append(name)
    return tuple(verified)


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("assets", nargs="+", type=Path)
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    repository = env.get("GITHUB_REPOSITORY", "")
    tag = env.get("GITHUB_REF_NAME", "")
    token = env.get("GITHUB_TOKEN", "")
    if not repository or not tag or not token:
        raise ValueError("GITHUB_REPOSITORY, GITHUB_REF_NAME, and GITHUB_TOKEN are required")

    remote_digests = fetch_release_asset_digests(repository, tag, token)
    verified = verify_existing_assets(args.assets, remote_digests)
    if verified:
        print(f"Verified existing GitHub release assets: {', '.join(verified)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
