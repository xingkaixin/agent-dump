"""Synthetic databases shared by SQLite Provider CLI contracts."""

from contextlib import closing
import importlib
import json
import os
import sqlite3

from cli_fixture import ROOT

NOW = 1768478400000


def create_v2(cli, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests" / "cli"))
    fixtures = importlib.import_module("opencode_fixtures")
    path = cli.root / "sources/sqlite" / ("session #库.db" if os.name == "nt" else "session #?库.db")
    fixtures.create_opencode_v2_db(path, NOW)
    cli.environment["OPENCODE_DB"] = str(path)
    return path


def create_legacy(cli, provider="opencode", *, path=None):
    if path is None:
        if provider == "zcode":
            home = cli.root / "sources/zcode-home"
            cli.environment.update(HOME=str(home), USERPROFILE=str(home))
            path = home / ".zcode/cli/db/db.sqlite"
        else:
            path = cli.root / "sources/sqlite/legacy.db"
            cli.environment["OPENCODE_DB"] = str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
            CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
                time_updated INTEGER, slug TEXT, directory TEXT, version TEXT, summary_files TEXT);
            CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
            CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, time_created INTEGER, data TEXT);
        """)
        connection.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ses_old",
                "Legacy 会话",
                NOW,
                NOW + 1000,
                "old-slug",
                "/workspace/legacy",
                "1.0",
                '["first.py", "second.py"]',
            ),
        )
        for identity, stamp, data in [
            ("msg_user", NOW, {"role": "user"}),
            (
                "msg_assistant",
                NOW + 1,
                {
                    "role": "assistant",
                    "agent": "build",
                    "mode": "normal",
                    "modelID": "model-first",
                    "providerID": "provider",
                    "time": {"completed": NOW + 3},
                    "tokens": {"input": 7, "output": 3},
                    "cost": 0.5,
                },
            ),
            ("msg_developer", NOW + 2, {"role": "developer", "modelID": "model-last"}),
        ]:
            connection.execute("INSERT INTO message VALUES (?, 'ses_old', ?, ?)", (identity, stamp, json.dumps(data)))
        for index, (owner, kind, body) in enumerate(
            [
                ("msg_user", "text", "Prompt"),
                ("msg_assistant", "reasoning", "Think"),
                ("msg_assistant", "text", "Answer"),
                ("msg_developer", "text", "Internal context"),
            ]
        ):
            connection.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?)",
                (f"part_{index}", owner, NOW + index, json.dumps({"type": kind, "text": body})),
            )
    return path


def export(cli, provider="opencode", identity="ses_v2", *, lang="en"):
    cli.parity(
        f"{provider}://{identity}",
        "--format",
        "json,md,raw,print",
        "--output",
        "exports",
        "--lang",
        lang,
        formats=("json", "markdown", "raw-json"),
    )
    directory = cli.root / "exports" / provider
    return json.loads((directory / f"{identity}.json").read_text())
