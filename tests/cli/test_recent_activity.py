"""Activity windows use Session update facts across file and database sources."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3

from cli_fixture import CliFixture, header, message, write_jsonl
import pytest
from test_tui import terminal


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
        for index, (identity, (created, updated)) in enumerate(zip(ids, times, strict=True)):
            path = write_jsonl(
                cli.source.parent / f"rollout-{identity}.jsonl",
                [
                    header(identity, timestamp=created.isoformat()),
                    message("user", "activity-marker", stamp=updated.isoformat()),
                ],
            )
            modified = created if index < 2 else now
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
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_activity_window_finds_old_sessions_and_preserves_created_default(
    cli: CliFixture, provider: str, lang: str
) -> None:
    ids, _ = activity_sessions(cli, provider)
    before = cli.fixtures.source_manifest(cli.root)
    args = ("--list", "-d", "7", "-q", f"provider:{provider}", "--json", "--lang", lang)
    default = cli.run("rust", *args)
    explicit = cli.run("rust", *args, "--time-field", "created")
    assert default.returncode == explicit.returncode == 0
    assert (default.stdout, default.stderr) == (explicit.stdout, explicit.stderr)
    assert [item["id"] for item in json.loads(default.stdout)["data"]] == [ids[2]]
    recent = cli.run("rust", *args, "--time-field=updated")
    assert recent.returncode == 0 and not recent.stderr
    records = json.loads(recent.stdout)["data"]
    assert [item["id"] for item in records] == [ids[1], ids[0]]
    assert all(item["created_at"] < item["updated_at"] for item in records)
    limited = cli.run("rust", "--time-field", "updated", "-d", "7", "-q", f"provider:{provider} limit:1", "--json")
    assert limited.returncode == 0, limited.stderr
    assert [item["id"] for item in json.loads(limited.stdout)["data"]] == [ids[1]]
    searched = cli.run(
        "rust",
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


@pytest.mark.parametrize("lang,today,basis", [("en", "Today", "updated time"), ("zh", "今天", "按更新时间")])
def test_activity_dates_and_selector_groups_follow_updated_time(
    cli: CliFixture, lang: str, today: str, basis: str
) -> None:
    ids, now = activity_sessions(cli, "codex")
    args = ("--time-field", "updated", "-d", "7", "-q", "provider:codex", "--no-metadata-summary", "--lang", lang)
    listed = cli.run("rust", "--list", *args)
    assert listed.returncode == 0, listed.stderr
    assert basis in listed.stdout
    assert now.strftime("%Y-%m-%d %H:%M") in listed.stdout
    assert listed.stdout.index(ids[1]) < listed.stdout.index(ids[0])
    selected = cli.run("rust", "--interactive", *args, stdin="q\n")
    assert selected.returncode == 1 and not selected.stderr
    assert f"[{today}]" in selected.stdout
    assert (now - timedelta(days=200)).strftime("%Y-%m-%d") not in selected.stdout
    assert not (cli.root / "sessions").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--collect", "--dry-run"],
        ["--stats"],
        ["--reindex"],
        ["--providers"],
        ["codex://missing", "--head", "--json"],
        ["codex://missing", "--read", "--json"],
    ],
)
def test_activity_basis_rejects_unsupported_modes(cli: CliFixture, args: list[str]) -> None:
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("rust", *args, "--time-field", "updated")
    assert result.returncode == 1 and result.stderr
    assert not result.stdout
    assert cli.fixtures.source_manifest(cli.root) == before
    assert not list(cli.root.glob("agent-dump-collect*.md"))


@pytest.mark.skipif(os.name == "nt", reason="Real PTY; list and selector contracts are portable")
def test_reader_can_open_an_old_recently_updated_session(cli: CliFixture) -> None:
    activity_sessions(cli, "codex")
    before = cli.fixtures.source_manifest(cli.root)
    with terminal(cli, "--browse", "--time-field", "updated", "-d", "7", "-q", "provider:codex") as (
        expect,
        send,
        _,
        finish,
    ):
        expect("codex://activity-1")
        send("\t")
        expect("activity-marker")
        send("q")
        code, transcript = finish()
        assert code == 0, transcript
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("args", [["--time-field", "modified"], ["--time-field", "updated", "-d", "0"]])
def test_invalid_activity_arguments(cli: CliFixture, args: list[str]) -> None:
    result = cli.run("rust", *args, "--json")
    assert result.returncode == 2 and result.stderr
    assert not result.stdout
