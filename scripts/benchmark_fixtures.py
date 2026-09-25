"""Deterministic, synthetic Provider sources for cross-language CLI benchmarks."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

FIXTURE_VERSION = 1
EPOCH = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Profile:
    sessions_per_provider: int
    messages_per_session: int
    text_chars: int
    large_text_chars: int


PROFILES = {
    "smoke": Profile(8, 4, 128, 64 * 1024),
    "standard": Profile(500, 20, 256, 8 * 1024 * 1024),
    "large": Profile(2000, 40, 1024, 32 * 1024 * 1024),
}


def codex_id(index: int) -> str:
    return f"019c213e-c251-73a3-af66-{index:012x}"


def session_text(index: int, message: int, chars: int) -> str:
    fragment = f"Session {index} message {message}: benchmark payload 中文段落，记录处理结果。\n"
    body = (fragment * (chars // len(fragment) + 1))[:chars]
    marker = "quartz 迁移验证" if index % 10 == 0 else "basalt 常规处理"
    return f"{body}\n{marker} end-{index}-{message}"


def session_messages(profile: Profile, index: int) -> list[tuple[str, str]]:
    large = index == profile.sessions_per_provider
    count = 2 if large else profile.messages_per_session
    return [
        (
            "user" if message % 2 == 0 else "assistant",
            session_text(index, message, profile.large_text_chars if large and message == 1 else profile.text_chars),
        )
        for message in range(count)
    ]


def isolated_environment(root: Path) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if key in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}
    }
    locations = {
        "HOME": "home",
        "USERPROFILE": "home",
        "XDG_DATA_HOME": "data",
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "APPDATA": "appdata",
        "LOCALAPPDATA": "localappdata",
        "CODEX_HOME": "sources/codex",
        "CLAUDE_CONFIG_DIR": "sources/claude",
        "KIMI_SHARE_DIR": "sources/kimi",
        "PI_HOME": "sources/pi",
        "DEEPCHAT_USER_DATA_DIR": "sources/deepchat",
        "CHERRY_STUDIO_USER_DATA_DIR": "sources/cherry",
        "MINIMAX_DATA_DIR": "sources/minimax",
        "MAVIS_DATA_DIR": "sources/minimax",
        "TMPDIR": "tmp",
        "TMP": "tmp",
        "TEMP": "tmp",
    }
    for name, relative in locations.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        environment[name] = str(path)
    environment.update(
        OPENCODE_DB=str(root / "sources" / "opencode.db"),
        TZ="UTC",
        LANG="C.UTF-8",
        LC_ALL="C.UTF-8",
        NO_COLOR="1",
        TERM="dumb",
        PYTHONHASHSEED="0",
        PYTHONIOENCODING="utf-8",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return environment


def write_codex(root: Path, profile: Profile) -> None:
    home = root / "sources" / "codex"
    sessions = home / "sessions" / "2026" / "01" / "15"
    sessions.mkdir(parents=True, exist_ok=True)
    titles = []
    for index in range(profile.sessions_per_provider + 1):
        identity = codex_id(index)
        created = EPOCH + timedelta(seconds=index)
        records: list[dict[str, Any]] = [
            {
                "type": "session_meta",
                "payload": {
                    "id": identity,
                    "timestamp": created.isoformat(),
                    "cwd": "/benchmark/project",
                    "cli_version": "benchmark-v1",
                    "model_provider": "openai",
                },
            }
        ]
        for message, (role, body) in enumerate(session_messages(profile, index)):
            records.append(
                {
                    "type": "response_item",
                    "timestamp": (created + timedelta(seconds=message + 1)).isoformat(),
                    "payload": {
                        "type": "message",
                        "role": role,
                        "content": [{"type": "input_text" if role == "user" else "output_text", "text": body}],
                    },
                }
            )
        path = sessions / f"rollout-2026-01-15T12-00-00-{identity}.jsonl"
        path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
        os.utime(path, (created.timestamp(), created.timestamp()))
        titles.append({"id": identity, "thread_name": f"Codex benchmark {index:05d}"})
    (home / "session_index.jsonl").write_text("".join(json.dumps(title) + "\n" for title in titles), encoding="utf-8")


def write_opencode(root: Path, profile: Profile) -> None:
    with sqlite3.connect(root / "sources" / "opencode.db") as connection:
        connection.executescript("""
            CREATE TABLE session_v2 (
                id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, slug TEXT,
                directory TEXT, title TEXT, version TEXT, summary_files INTEGER,
                model TEXT, cost REAL, tokens_input INTEGER, tokens_output INTEGER,
                time_created INTEGER, time_updated INTEGER
            );
            CREATE TABLE session_message (
                id TEXT PRIMARY KEY, session_id TEXT, type TEXT, seq INTEGER,
                time_created INTEGER, time_updated INTEGER, data TEXT
            );
            CREATE UNIQUE INDEX session_message_session_seq_idx ON session_message(session_id, seq);
        """)
        for index in range(profile.sessions_per_provider):
            identity = f"ses_bench_{index:06d}"
            created = int((EPOCH + timedelta(seconds=index)).timestamp() * 1000)
            connection.execute(
                "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identity,
                    "project_benchmark",
                    None,
                    f"bench-{index}",
                    "/benchmark/project",
                    f"OpenCode benchmark {index:05d}",
                    "2.0.15",
                    0,
                    json.dumps({"id": "benchmark-model", "providerID": "openai"}),
                    0,
                    0,
                    0,
                    created,
                    created + profile.messages_per_session * 1000,
                ),
            )
            for message, (role, body) in enumerate(session_messages(profile, index)):
                data = {"text": body} if role == "user" else {"content": [{"type": "text", "text": body}]}
                connection.execute(
                    "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{identity}_{message}",
                        identity,
                        role,
                        message,
                        created + (message + 1) * 1000,
                        created + (message + 1) * 1000,
                        json.dumps(data, ensure_ascii=False),
                    ),
                )


def source_manifest(root: Path) -> dict[str, Any]:
    sources = root / "sources"
    digest = hashlib.sha256()
    size = count = 0
    for path in sorted(sources.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(sources).as_posix().encode())
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        count += 1
    return {"sha256": digest.hexdigest(), "bytes": size, "files": count}


def create_fixture(root: Path, profile: Profile) -> dict[str, str]:
    environment = isolated_environment(root)
    write_codex(root, profile)
    write_opencode(root, profile)
    return environment
