"""Date-range filtering (--since/--until) across list, search, and stats modes."""

from datetime import datetime, timedelta, timezone
import json
import os

from cli_fixture import CliFixture, header, message, write_jsonl
import pytest


def _seed_sessions(cli: CliFixture) -> dict[str, tuple[str, str]]:
    """Create isolated codex sessions with known UTC/local dates under UTC TZ."""
    cli.environment["TZ"] = "UTC"
    for path in cli.source.parent.glob("*.jsonl"):
        path.unlink()
    today = datetime.now(timezone.utc).date()
    d_old = today - timedelta(days=40)
    d_mid = today - timedelta(days=20)
    d_recent = today - timedelta(days=5)
    # s_old_updated_recent: created 40 days ago, updated 5 days ago
    # s_mid: created 20 days ago, updated 20 days ago
    # s_recent_created_old_updated: created 5 days ago, updated 40 days ago
    specs = {
        "old-updated-recent": (d_old, d_recent, "alpha-date-marker"),
        "mid-both": (d_mid, d_mid, "alpha-date-marker"),
        "recent-created": (d_recent, d_old, "alpha-date-marker"),
    }
    for sid, (created_d, updated_d, text) in specs.items():
        created = datetime(created_d.year, created_d.month, created_d.day, 12, 0, tzinfo=timezone.utc)
        updated = datetime(updated_d.year, updated_d.month, updated_d.day, 12, 0, tzinfo=timezone.utc)
        path = write_jsonl(
            cli.source.parent / f"rollout-{sid}.jsonl",
            [
                header(sid, timestamp=created.isoformat()),
                message("user", text, stamp=updated.isoformat()),
            ],
        )
        modified = max(created, updated)
        os.utime(path, (modified.timestamp(), modified.timestamp()))
    return {
        "old": (d_old.isoformat(), d_old.strftime("%Y%m%d")),
        "mid": (d_mid.isoformat(), d_mid.strftime("%Y%m%d")),
        "recent": (d_recent.isoformat(), d_recent.strftime("%Y%m%d")),
        "today": (today.isoformat(), today.strftime("%Y%m%d")),
    }


def test_list_search_stats_date_range_and_time_field(cli: CliFixture) -> None:
    dates = _seed_sessions(cli)
    before = cli.fixtures.source_manifest(cli.root)

    # Default time_field=updated: mid..mid matches only mid-both (YYYY-MM-DD and YYYYMMDD)
    listed = cli.run(
        "--list",
        "--since",
        dates["mid"][0],
        "--until",
        dates["mid"][1],
        "-q",
        "provider:codex",
        "--json",
    )
    assert listed.returncode == 0 and not listed.stderr, listed.stderr
    assert [item["id"] for item in json.loads(listed.stdout)["data"]] == ["mid-both"]

    # Text output displays the explicit date range header without --since ignored warning
    listed_text = cli.run(
        "list",
        "--since",
        dates["mid"][0],
        "--until",
        dates["mid"][0],
        "-q",
        "provider:codex",
        "--lang",
        "en",
    )
    assert listed_text.returncode == 0 and not listed_text.stderr
    assert f"{dates['mid'][0]} ~ {dates['mid'][0]}" in listed_text.stdout
    assert "will be ignored" not in listed_text.stdout

    # --time-field created: recent..recent selects recent-created instead of old-updated-recent
    by_created = cli.run(
        "--list",
        "--time-field",
        "created",
        "--since",
        dates["recent"][0],
        "--until",
        dates["recent"][0],
        "-q",
        "provider:codex",
        "--json",
    )
    assert by_created.returncode == 0 and not by_created.stderr
    assert [item["id"] for item in json.loads(by_created.stdout)["data"]] == ["recent-created"]

    # --search with explicit date range (default updated) selects old-updated-recent in recent..today
    searched = cli.run(
        "--search",
        "alpha-date-marker",
        "--since",
        dates["recent"][0],
        "-q",
        "provider:codex",
        "--json",
    )
    assert searched.returncode == 0 and not searched.stderr
    assert [item["id"] for item in json.loads(searched.stdout)["data"]] == ["old-updated-recent"]

    # --stats stays fixed on created_at: mid..recent includes mid-both + recent-created (2 sessions)
    stats = cli.run(
        "--stats",
        "--since",
        dates["mid"][0],
        "--until",
        dates["recent"][0],
        "-q",
        "provider:codex",
        "--json",
    )
    assert stats.returncode == 0 and not stats.stderr
    assert json.loads(stats.stdout)["data"]["by_provider"]["codex"]["sessions"] == 2

    # Explicit --since/--until overrides --days (even -d 1)
    override = cli.run(
        "--list",
        "-d",
        "1",
        "--since",
        dates["mid"][0],
        "--until",
        dates["mid"][0],
        "-q",
        "provider:codex",
        "--json",
    )
    assert override.returncode == 0 and not override.stderr
    assert [item["id"] for item in json.loads(override.stdout)["data"]] == ["mid-both"]

    # Implicit list mode when passing --since/--until without --list
    implicit = cli.run(
        "--since",
        dates["mid"][0],
        "--until",
        dates["mid"][0],
        "--json",
    )
    assert implicit.returncode == 0 and not implicit.stderr
    assert [item["id"] for item in json.loads(implicit.stdout)["data"] if item["uri"].startswith("codex://")] == [
        "mid-both"
    ]

    assert cli.fixtures.source_manifest(cli.root) == before


def test_until_only_starts_at_first_of_month(cli: CliFixture) -> None:
    cli.environment["TZ"] = "UTC"
    for path in cli.source.parent.glob("*.jsonl"):
        path.unlink()
    specs = {
        "prev-month": datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc),
        "in-month": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        "after-until": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
    }
    for sid, stamp in specs.items():
        path = write_jsonl(
            cli.source.parent / f"rollout-{sid}.jsonl",
            [header(sid, timestamp=stamp.isoformat()), message("user", "month-check", stamp=stamp.isoformat())],
        )
        os.utime(path, (stamp.timestamp(), stamp.timestamp()))

    result = cli.run("--list", "--until", "2026-03-10", "-q", "provider:codex", "--json")
    assert result.returncode == 0 and not result.stderr
    assert [item["id"] for item in json.loads(result.stdout)["data"]] == ["in-month"]


@pytest.mark.parametrize(
    ("mode_args", "date_args", "expected"),
    [
        (["--list"], ["--since", "2026-02-30"], "❌ Invalid date format. Use YYYY-MM-DD or YYYYMMDD."),
        (
            ["--list"],
            ["--since", "2026-03-10", "--until", "2026-03-01"],
            "❌ Invalid date range: since must be <= until.",
        ),
        (["--stats"], ["--since", "bad-date"], "❌ Invalid date format. Use YYYY-MM-DD or YYYYMMDD."),
        (
            ["--search", "hello"],
            ["--since", "2026-03-10", "--until", "2026-03-01"],
            "❌ Invalid date range: since must be <= until.",
        ),
    ],
)
def test_invalid_date_format_and_range_fail_cleanly(
    cli: CliFixture,
    mode_args: list[str],
    date_args: list[str],
    expected: str,
) -> None:
    text = cli.run(*mode_args, *date_args, "--lang", "en")
    assert text.returncode == 1
    assert text.stdout.splitlines()[0] == expected
    assert not text.stderr

    machine = cli.run(*mode_args, *date_args, "--json", "--lang", "en")
    assert machine.returncode == 1
    assert not machine.stdout
    assert machine.stderr.splitlines()[0] == expected
