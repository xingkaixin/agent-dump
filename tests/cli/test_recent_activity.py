"""Activity windows use Session update facts across file and database sources."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3

from cli_fixture import CliFixture, header, message, write_jsonl
import pytest


def activity_sessions(cli: CliFixture, provider: str) -> tuple[list[str], datetime]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    times = [
        (now - timedelta(days=100), now - timedelta(days=1)),
        (now - timedelta(days=200), now),
        (now - timedelta(days=1), now - timedelta(days=90)),
        (now - timedelta(days=100), now - timedelta(days=90)),
    ]
    if provider == "codex":
        for path in cli.source.parent.glob("*.jsonl"):
            path.unlink()
        ids = [f"activity-{index}" for index in range(len(times))]
        for identity, (created, updated) in zip(ids, times, strict=True):
            path = write_jsonl(
                cli.source.parent / f"rollout-{identity}.jsonl",
                [
                    header(identity, timestamp=created.isoformat()),
                    message("user", "activity-marker", stamp=updated.isoformat()),
                ],
            )
            modified = max(created, updated)
            os.utime(path, (modified.timestamp(), modified.timestamp()))
    else:
        ids = [f"ses_bench_{index:06d}" for index in range(len(times))]
        with closing(sqlite3.connect(cli.environment["OPENCODE_DB"])) as connection, connection:
            old = int((now - timedelta(days=300)).timestamp() * 1000)
            connection.execute("UPDATE session_v2 SET time_created = ?, time_updated = ?", (old, old))
            for identity, (created, updated) in zip(ids, times, strict=True):
                connection.execute(
                    "UPDATE session_v2 SET title = 'activity-marker', time_created = ?, time_updated = ? WHERE id = ?",
                    (int(created.timestamp() * 1000), int(updated.timestamp() * 1000), identity),
                )
    return ids, now


@pytest.mark.parametrize("provider", ["codex", "opencode"])
def test_activity_window_defaults_to_updated_time(cli: CliFixture, provider: str) -> None:
    ids, _ = activity_sessions(cli, provider)
    before = cli.fixtures.source_manifest(cli.root)
    args = ("--list", "-d", "7", "-q", f"provider:{provider}", "--json")
    created = cli.run(*args, "--time-field", "created")
    assert created.returncode == 0, created.stderr
    assert [item["id"] for item in json.loads(created.stdout)["data"]] == [ids[2]]
    recent = cli.run(*args)
    explicit = cli.run(*args, "--time-field=updated")
    assert recent.returncode == explicit.returncode == 0 and not recent.stderr
    assert recent.stdout == explicit.stdout
    records = json.loads(recent.stdout)["data"]
    assert [item["id"] for item in records] == [ids[1], ids[0]]
    assert all(item["created_at"] < item["updated_at"] for item in records)
    limited = cli.run("--time-field", "updated", "-d", "7", "-q", f"provider:{provider} limit:1", "--json")
    assert limited.returncode == 0, limited.stderr
    assert [item["id"] for item in json.loads(limited.stdout)["data"]] == [ids[1]]
    searched = cli.run(
        "--search",
        "activity-marker",
        "--time-field",
        "updated",
        "-d",
        "7",
        "-q",
        f"provider:{provider}",
        "--json",
    )
    assert searched.returncode == 0, searched.stderr
    matches = json.loads(searched.stdout)["data"]
    assert {item["id"] for item in matches} == {ids[0], ids[1]}
    assert [item["rank"] for item in matches] == sorted((item["rank"] for item in matches), reverse=True)
    assert cli.fixtures.source_manifest(cli.root) == before


def test_stats_window_keeps_created_time(cli: CliFixture) -> None:
    activity_sessions(cli, "codex")
    result = cli.run("--stats", "-d", "7", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["by_provider"]["codex"]["sessions"] == 1


@pytest.mark.parametrize(
    "args",
    [
        ["--collect", "--dry-run"],
        ["--stats"],
    ],
)
def test_activity_basis_rejects_unsupported_modes(cli: CliFixture, args: list[str]) -> None:
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(*args, "--time-field", "updated")
    assert result.returncode == 1 and result.stderr
    assert not result.stdout
    assert cli.fixtures.source_manifest(cli.root) == before
    assert not list(cli.root.glob("agent-dump-collect*.md"))
