from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pytest

from agent_dump.agent_registry import AGENT_REGISTRATIONS
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.agents.claudecode import ClaudeCodeAgent
from agent_dump.agents.codex import CodexAgent
from agent_dump.agents.cursor import CursorAgent
from agent_dump.agents.kimi import KimiAgent
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.agents.pi import PiAgent
from agent_dump.agents.zcode import ZCodeAgent
from agent_dump.diagnostics import DiagnosticFileNotFoundError
from agent_dump.rendering import export_session_in_format, format_session_metadata_summary, render_session_head


@dataclass(frozen=True)
class ProviderContractFixture:
    agent: BaseAgent
    session_id: str
    uri: str
    title: str
    location: str
    model: str | None
    head_message_count: int
    data_message_count: int
    texts: tuple[str, ...]
    remove_source: Callable[[], None]
    subtargets: tuple[str, ...] = ()


ProviderBuilder = Callable[[pytest.MonkeyPatch, Path], ProviderContractFixture]


def _jsonl_line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(_jsonl_line(record) for record in records) + "\n", encoding="utf-8")


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _create_cursor_global_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_cursor_kv(path: Path, key: str, value: dict[str, Any]) -> None:
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO cursorDiskKV(key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _cursor_user_root(cursor_home: Path) -> Path:
    if os.name == "nt":
        return cursor_home / "AppData" / "Roaming" / "Cursor" / "User"
    if sys.platform.startswith("darwin"):
        return cursor_home / "Library" / "Application Support" / "Cursor" / "User"
    return cursor_home / ".config" / "Cursor" / "User"


def _create_opencode_db(path: Path, now_ms: int) -> None:
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                title TEXT,
                time_created INTEGER,
                time_updated INTEGER,
                slug TEXT,
                directory TEXT,
                version INTEGER,
                summary_files TEXT
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                time_created INTEGER,
                data TEXT
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT,
                time_created INTEGER,
                data TEXT
            );
            """
        )
        cur.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "opencode-contract",
                "OpenCode Contract",
                now_ms,
                now_ms + 1000,
                "opencode-contract",
                "/workspace/opencode-contract",
                1,
                '["src/main.py"]',
            ),
        )
        messages = [
            ("opencode-user", now_ms, {"role": "user", "modelID": "gpt-4.1"}),
            ("opencode-assistant", now_ms + 1000, {"role": "assistant", "modelID": "gpt-4.1"}),
        ]
        cur.executemany(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            [
                (message_id, "opencode-contract", created_at, json.dumps(payload, ensure_ascii=False))
                for message_id, created_at, payload in messages
            ],
        )
        parts = [
            ("opencode-user-part", "opencode-user", now_ms, {"type": "text", "text": "OpenCode prompt"}),
            (
                "opencode-assistant-part",
                "opencode-assistant",
                now_ms + 1000,
                {"type": "text", "text": "OpenCode answer"},
            ),
        ]
        cur.executemany(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            [
                (part_id, message_id, created_at, json.dumps(payload, ensure_ascii=False))
                for part_id, message_id, created_at, payload in parts
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _create_zcode_db(path: Path, now_ms: int) -> None:
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                slug TEXT NOT NULL,
                directory TEXT NOT NULL,
                path TEXT,
                title TEXT NOT NULL,
                version TEXT NOT NULL,
                summary_files TEXT,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'interactive',
                title_source TEXT NOT NULL DEFAULT 'first_input'
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            INSERT INTO session (
                id, project_id, slug, directory, path, title, version, summary_files,
                time_created, time_updated, task_type, title_source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "zcode-contract",
                "proj-zcode-contract",
                "zcode-contract",
                "/workspace/zcode-contract",
                "/workspace/zcode-contract",
                "ZCode Contract",
                "0.14.8",
                '["web/app.tsx"]',
                now_ms,
                now_ms + 1000,
                "interactive",
                "first_input",
            ),
        )
        messages = [
            ("zcode-user", now_ms, {"role": "user", "modelID": "GLM-5.2"}),
            ("zcode-assistant", now_ms + 1000, {"role": "assistant", "modelID": "GLM-5.2"}),
        ]
        cur.executemany(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            [
                (message_id, "zcode-contract", created_at, created_at, json.dumps(payload, ensure_ascii=False))
                for message_id, created_at, payload in messages
            ],
        )
        parts = [
            ("zcode-user-part", "zcode-user", now_ms, {"type": "text", "text": "ZCode prompt"}),
            (
                "zcode-assistant-part",
                "zcode-assistant",
                now_ms + 1000,
                {"type": "text", "text": "ZCode answer"},
            ),
        ]
        cur.executemany(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    part_id,
                    message_id,
                    "zcode-contract",
                    created_at,
                    created_at,
                    json.dumps(payload, ensure_ascii=False),
                )
                for part_id, message_id, created_at, payload in parts
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _build_codex_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProviderContractFixture:
    now = datetime.now(timezone.utc)
    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions"
    sessions_dir.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    session_path = sessions_dir / "rollout-2026-01-01T00-00-00-codex-contract.jsonl"
    _write_jsonl(
        session_path,
        [
            {
                "type": "session_meta",
                "timestamp": now.isoformat(),
                "payload": {
                    "id": "codex-contract",
                    "timestamp": now.isoformat(),
                    "cwd": "/workspace/codex-contract",
                    "cli_version": "1.0.0",
                    "model_provider": "openai",
                },
            },
            {
                "type": "response_item",
                "timestamp": now.isoformat(),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Codex prompt"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": now.isoformat(),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Codex Contract"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": now.isoformat(),
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "model": "gpt-5.4-mini",
                    "content": [{"type": "output_text", "text": "Codex answer"}],
                },
            },
        ],
    )

    return ProviderContractFixture(
        agent=CodexAgent(),
        session_id="codex-contract",
        uri="codex://codex-contract",
        title="Codex Contract",
        location="/workspace/codex-contract",
        model="gpt-5.4-mini",
        head_message_count=3,
        data_message_count=3,
        texts=("Codex prompt", "Codex Contract", "Codex answer"),
        remove_source=lambda: session_path.unlink(),
    )


def _build_claude_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProviderContractFixture:
    now = datetime.now(timezone.utc)
    claude_root = tmp_path / "claude-root"
    project_dir = claude_root / "projects" / "project-contract"
    project_dir.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_root))

    session_path = project_dir / "claude-contract.jsonl"
    _write_jsonl(
        session_path,
        [
            {
                "type": "user",
                "uuid": "claude-user",
                "timestamp": now.isoformat(),
                "cwd": "/workspace/claude-contract",
                "version": "1.0.0",
                "message": {"role": "user", "content": "Claude prompt"},
            },
            {
                "type": "assistant",
                "uuid": "claude-assistant",
                "timestamp": now.isoformat(),
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4.5",
                    "content": [{"type": "text", "text": "Claude answer"}],
                },
            },
        ],
    )

    return ProviderContractFixture(
        agent=ClaudeCodeAgent(),
        session_id="claude-contract",
        uri="claude://claude-contract",
        title="Claude prompt",
        location="/workspace/claude-contract",
        model="claude-sonnet-4.5",
        head_message_count=2,
        data_message_count=2,
        texts=("Claude prompt", "Claude answer"),
        remove_source=lambda: session_path.unlink(),
    )


def _build_kimi_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProviderContractFixture:
    now_ts = datetime.now(timezone.utc).timestamp()
    kimi_root = tmp_path / "kimi-root"
    sessions_root = kimi_root / "sessions"
    cwd = "/workspace/kimi-contract"
    project_hash = hashlib.md5(cwd.encode("utf-8")).hexdigest()  # noqa: S324
    session_dir = sessions_root / project_hash / "kimi-contract"
    session_dir.mkdir(parents=True)
    monkeypatch.setenv("KIMI_SHARE_DIR", str(kimi_root))

    (kimi_root / "kimi.json").write_text(json.dumps({"work_dirs": [{"path": cwd}]}), encoding="utf-8")
    (session_dir / "metadata.json").write_text(
        json.dumps(
            {
                "session_id": "kimi-contract",
                "title": "Kimi Contract",
                "wire_mtime": now_ts,
                "title_generated": False,
            }
        ),
        encoding="utf-8",
    )
    context_path = session_dir / "context.jsonl"
    _write_jsonl(
        context_path,
        [
            {"role": "user", "content": "Kimi prompt"},
            {"role": "assistant", "content": [{"type": "text", "text": "Kimi answer"}]},
        ],
    )

    return ProviderContractFixture(
        agent=KimiAgent(),
        session_id="kimi-contract",
        uri="kimi://kimi-contract",
        title="Kimi Contract",
        location=cwd,
        model=None,
        head_message_count=2,
        data_message_count=2,
        texts=("Kimi prompt", "Kimi answer"),
        remove_source=lambda: context_path.unlink(),
    )


def _build_opencode_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProviderContractFixture:
    now = _now_ms()
    data_home = tmp_path / "data-home"
    db_path = data_home / "opencode" / "opencode.db"
    db_path.parent.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    _create_opencode_db(db_path, now)

    return ProviderContractFixture(
        agent=OpenCodeAgent(),
        session_id="opencode-contract",
        uri="opencode://opencode-contract",
        title="OpenCode Contract",
        location="/workspace/opencode-contract",
        model="gpt-4.1",
        head_message_count=2,
        data_message_count=2,
        texts=("OpenCode prompt", "OpenCode answer"),
        remove_source=lambda: db_path.unlink(),
        subtargets=("src/main.py",),
    )


def _build_zcode_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProviderContractFixture:
    now = _now_ms()
    zcode_home = tmp_path / "zcode-home"
    db_path = zcode_home / ".zcode" / "cli" / "db" / "db.sqlite"
    db_path.parent.mkdir(parents=True)
    monkeypatch.setattr("agent_dump.agents.zcode.sys.platform", "darwin")
    monkeypatch.setattr("agent_dump.agents.zcode.Path.home", lambda: zcode_home)
    _create_zcode_db(db_path, now)

    return ProviderContractFixture(
        agent=ZCodeAgent(),
        session_id="zcode-contract",
        uri="zcode://zcode-contract",
        title="ZCode Contract",
        location="/workspace/zcode-contract",
        model="GLM-5.2",
        head_message_count=2,
        data_message_count=2,
        texts=("ZCode prompt", "ZCode answer"),
        remove_source=lambda: db_path.unlink(),
        subtargets=("web/app.tsx",),
    )


def _build_cursor_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProviderContractFixture:
    now = _now_ms()
    cursor_home = tmp_path / "cursor-home"
    workspace_root = tmp_path / "workspaceStorage"
    global_db = _cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
    workspace_root.mkdir(parents=True)
    global_db.parent.mkdir(parents=True)
    monkeypatch.setenv("CURSOR_DATA_PATH", str(workspace_root))
    monkeypatch.setattr("agent_dump.agents.cursor.Path.home", lambda: cursor_home)
    _create_cursor_global_db(global_db)

    _insert_cursor_kv(
        global_db,
        "composerData:cursor-composer",
        {
            "composerId": "cursor-composer",
            "name": "Cursor Contract",
            "createdAt": now,
            "updatedAt": now + 4000,
            "modelConfig": {"modelName": "claude-4.6"},
            "subagentComposerIds": ["cursor-worker"],
        },
    )
    _insert_cursor_kv(
        global_db,
        "bubbleId:cursor-composer:b1",
        {
            "requestId": "cursor-request",
            "type": 1,
            "text": "Cursor prompt",
            "modelInfo": {"modelName": "claude-4.6"},
            "timingInfo": {"clientRpcSendTime": now},
        },
    )
    _insert_cursor_kv(
        global_db,
        "bubbleId:cursor-composer:b2",
        {"type": 2, "text": "\n\n\n", "timingInfo": {"clientRpcSendTime": now + 1000}},
    )
    _insert_cursor_kv(
        global_db,
        "bubbleId:cursor-composer:b3",
        {
            "type": 2,
            "timingInfo": {"clientRpcSendTime": now + 2000},
            "toolFormerData": {
                "name": "read_file_v2",
                "toolCallId": "tool-read",
                "status": "completed",
                "params": json.dumps({"targetFile": "/workspace/file.py"}, ensure_ascii=False),
                "result": "file body",
            },
        },
    )
    _insert_cursor_kv(
        global_db,
        "bubbleId:cursor-composer:b4",
        {
            "type": 2,
            "timingInfo": {"clientRpcSendTime": now + 3000},
            "toolFormerData": {
                "name": "task_v2",
                "toolCallId": "tool-task",
                "status": "completed",
                "params": json.dumps(
                    {
                        "prompt": "Summarize this fixture.",
                        "description": "Fixture worker",
                        "subagentType": "explore",
                    },
                    ensure_ascii=False,
                ),
                "result": json.dumps({"agentId": "cursor-worker"}, ensure_ascii=False),
                "additionalData": {
                    "status": "success",
                    "subagentComposerId": "cursor-worker",
                },
            },
        },
    )
    _insert_cursor_kv(
        global_db,
        "composerData:cursor-worker",
        {
            "composerId": "cursor-worker",
            "createdAt": now + 4000,
            "name": "Cursor Worker",
            "modelConfig": {"modelName": "cursor-worker-model"},
            "subagentInfo": {"parentComposerId": "cursor-composer", "subagentTypeName": "explore"},
        },
    )
    _insert_cursor_kv(
        global_db,
        "bubbleId:cursor-worker:c1",
        {
            "requestId": "cursor-worker-request",
            "type": 1,
            "text": "Summarize this fixture.",
            "timingInfo": {"clientRpcSendTime": now + 4000},
        },
    )
    _insert_cursor_kv(
        global_db,
        "bubbleId:cursor-worker:c2",
        {
            "type": 2,
            "text": "Cursor worker answer",
            "timingInfo": {"clientRpcSendTime": now + 5000},
        },
    )

    return ProviderContractFixture(
        agent=CursorAgent(),
        session_id="cursor-request",
        uri="cursor://cursor-request",
        title="Cursor Contract",
        location=str(global_db.parent),
        model="claude-4.6",
        head_message_count=4,
        data_message_count=4,
        texts=("Cursor prompt", "Cursor worker answer"),
        remove_source=lambda: global_db.unlink(),
        subtargets=("cursor-worker",),
    )


def _build_pi_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ProviderContractFixture:
    now = datetime.now(timezone.utc)
    pi_home = tmp_path / "pi-home"
    sessions_dir = pi_home / "agent" / "sessions" / "--workspace-pi-contract--"
    sessions_dir.mkdir(parents=True)
    monkeypatch.setenv("PI_HOME", str(pi_home))

    session_path = sessions_dir / "20260101_pi-contract.jsonl"
    _write_jsonl(
        session_path,
        [
            {
                "type": "session",
                "version": 3,
                "id": "pi-contract",
                "timestamp": now.isoformat(),
                "cwd": "/workspace/pi-contract",
            },
            {
                "type": "message",
                "id": "pi-user",
                "parentId": None,
                "timestamp": now.isoformat(),
                "message": {"role": "user", "content": "Pi prompt"},
            },
            {
                "type": "session_info",
                "id": "pi-info",
                "parentId": "pi-user",
                "timestamp": now.isoformat(),
                "name": "Pi Contract",
            },
            {
                "type": "message",
                "id": "pi-assistant",
                "parentId": "pi-user",
                "timestamp": now.isoformat(),
                "message": {
                    "role": "assistant",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-5",
                    "content": [{"type": "text", "text": "Pi answer"}],
                },
            },
        ],
    )

    return ProviderContractFixture(
        agent=PiAgent(),
        session_id="pi-contract",
        uri="pi://pi-contract",
        title="Pi Contract",
        location="/workspace/pi-contract",
        model="claude-sonnet-4-5",
        head_message_count=2,
        data_message_count=2,
        texts=("Pi prompt", "Pi answer"),
        remove_source=lambda: session_path.unlink(),
    )


CONTRACT_BUILDERS: dict[str, ProviderBuilder] = {
    "opencode": _build_opencode_contract,
    "zcode": _build_zcode_contract,
    "codex": _build_codex_contract,
    "kimi": _build_kimi_contract,
    "claudecode": _build_claude_contract,
    "cursor": _build_cursor_contract,
    "pi": _build_pi_contract,
}


def test_contract_builders_cover_registered_providers() -> None:
    registered_providers = {registration.name for registration in AGENT_REGISTRATIONS}

    assert set(CONTRACT_BUILDERS) == registered_providers


def _find_contract_session(fixture: ProviderContractFixture) -> Session:
    assert fixture.agent.is_available() is True
    sessions = fixture.agent.get_sessions(days=3650)
    session = next((item for item in sessions if item.id == fixture.session_id), None)
    assert session is not None, f"{fixture.agent.name} did not expose {fixture.session_id}"
    return session


@pytest.mark.parametrize(
    ("provider_name", "build_fixture"),
    CONTRACT_BUILDERS.items(),
    ids=CONTRACT_BUILDERS,
)
def test_provider_contract_scan_get_sessions_and_head(
    provider_name: str,
    build_fixture: ProviderBuilder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(monkeypatch, tmp_path)

    assert fixture.agent.name == provider_name
    assert fixture.agent.is_available() is True
    assert fixture.session_id in {session.id for session in fixture.agent.scan()}
    session = _find_contract_session(fixture)

    assert session.title == fixture.title
    assert session.created_at.tzinfo is not None
    assert session.created_at.utcoffset() == timezone.utc.utcoffset(session.created_at)
    assert session.updated_at.tzinfo is not None
    assert session.updated_at.utcoffset() == timezone.utc.utcoffset(session.updated_at)
    assert fixture.agent.get_session_uri(session) == fixture.uri

    head = fixture.agent.get_session_head(session)
    assert head["uri"] == fixture.uri
    assert head["agent"] == fixture.agent.display_name
    assert head["title"] == fixture.title
    assert head["cwd_or_project"] == fixture.location
    assert head["model"] == fixture.model
    assert head["message_count"] == fixture.head_message_count
    assert head["subtargets"] == list(fixture.subtargets)

    rendered = render_session_head(fixture.uri, head)
    assert "# Session Head" in rendered
    assert f"- URI: {fixture.uri}" in rendered

    summary = format_session_metadata_summary(fixture.agent, session)
    assert f"uri={fixture.uri}" in summary


@pytest.mark.parametrize("build_fixture", CONTRACT_BUILDERS.values(), ids=CONTRACT_BUILDERS)
def test_provider_contract_session_data_and_export_formats(
    build_fixture: ProviderBuilder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(monkeypatch, tmp_path)
    session = _find_contract_session(fixture)

    session_data = fixture.agent.get_session_data(session)
    assert session_data["id"] == fixture.session_id
    assert session_data["title"] == fixture.title
    assert isinstance(session_data["time_created"], int)
    assert isinstance(session_data["time_updated"], int)
    assert session_data["stats"]["message_count"] == fixture.data_message_count

    exported_text = json.dumps(session_data, ensure_ascii=False)
    for text in fixture.texts:
        assert text in exported_text
    assert "[empty message]" not in exported_text

    json_path = fixture.agent.export_session(session, tmp_path / "json")
    assert json_path.name == f"{fixture.session_id}.json"
    exported_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert exported_json["id"] == fixture.session_id
    assert exported_json["stats"]["message_count"] == fixture.data_message_count

    markdown_path = export_session_in_format(
        fixture.agent,
        session,
        tmp_path / "markdown",
        "markdown",
        session_data=session_data,
        session_uri=fixture.uri,
    )
    markdown = markdown_path.read_text(encoding="utf-8")
    assert markdown_path.name == f"{fixture.session_id}.md"
    assert f"- URI: `{fixture.uri}`" in markdown
    assert fixture.texts[0] in markdown


@pytest.mark.parametrize("build_fixture", CONTRACT_BUILDERS.values(), ids=CONTRACT_BUILDERS)
def test_provider_contract_export_paths_contain_untrusted_session_ids(
    build_fixture: ProviderBuilder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(monkeypatch, tmp_path)
    session = _find_contract_session(fixture)
    session_data = fixture.agent.get_session_data(session)
    unsafe_session = replace(session, id=str(tmp_path / "escaped"))
    monkeypatch.setattr(fixture.agent, "get_session_data", lambda _session: session_data)

    json_dir = tmp_path / "safe" / "json"
    json_path = fixture.agent.export_session(unsafe_session, json_dir)
    assert json_path == json_dir / "escaped.json"

    markdown_dir = tmp_path / "safe" / "markdown"
    markdown_path = export_session_in_format(
        fixture.agent,
        unsafe_session,
        markdown_dir,
        "markdown",
        session_data=session_data,
        session_uri=fixture.uri,
    )
    assert markdown_path == markdown_dir / "escaped.md"
    assert not (tmp_path / "escaped.json").exists()
    assert not (tmp_path / "escaped.md").exists()


@pytest.mark.parametrize("build_fixture", CONTRACT_BUILDERS.values(), ids=CONTRACT_BUILDERS)
def test_provider_contract_missing_source_diagnostic(
    build_fixture: ProviderBuilder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = build_fixture(monkeypatch, tmp_path)
    session = _find_contract_session(fixture)
    fixture.remove_source()

    with pytest.raises(DiagnosticFileNotFoundError) as exc_info:
        fixture.agent.get_session_data(session)

    assert exc_info.value.code == "source_missing"
    assert any("missing path:" in detail for detail in exc_info.value.details)
