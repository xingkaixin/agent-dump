"""测试 agents/zcode.py 模块。"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from agent_dump.agents.zcode import ZCodeAgent


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _create_zcode_db(path: Path) -> int:
    now = _now_ms()
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
                "sess-zcode",
                "proj-zcode",
                "sess-zcode",
                "/workspace/zcode",
                "/workspace/zcode",
                "ZCode Session",
                "0.14.8",
                '["web/page.tsx"]',
                now,
                now + 1000,
                "interactive",
                "first_input",
            ),
        )
        cur.executemany(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "msg-user",
                    "sess-zcode",
                    now,
                    now,
                    json.dumps({"role": "user", "modelID": "GLM-5.2"}, ensure_ascii=False),
                ),
                (
                    "msg-assistant",
                    "sess-zcode",
                    now + 1000,
                    now + 1000,
                    json.dumps(
                        {
                            "role": "assistant",
                            "modelID": "GLM-5.2",
                            "providerID": "builtin:bigmodel-coding-plan",
                            "tokens": {"input": 12, "output": 8},
                        },
                        ensure_ascii=False,
                    ),
                ),
            ],
        )
        cur.executemany(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "part-user",
                    "msg-user",
                    "sess-zcode",
                    now,
                    now,
                    json.dumps({"type": "text", "text": "ZCode prompt"}, ensure_ascii=False),
                ),
                (
                    "part-assistant",
                    "msg-assistant",
                    "sess-zcode",
                    now + 1000,
                    now + 1000,
                    json.dumps({"type": "text", "text": "ZCode answer"}, ensure_ascii=False),
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return now


def test_init() -> None:
    agent = ZCodeAgent()

    assert agent.name == "zcode"
    assert agent.display_name == "ZCode"
    assert agent.db_path is None


def test_find_db_path_on_macos(monkeypatch, tmp_path) -> None:
    agent = ZCodeAgent()
    db_path = tmp_path / ".zcode" / "cli" / "db" / "db.sqlite"
    db_path.parent.mkdir(parents=True)
    db_path.touch()

    monkeypatch.setattr("agent_dump.agents.zcode.sys.platform", "darwin")
    monkeypatch.setattr("agent_dump.agents.zcode.Path.home", lambda: tmp_path)

    assert agent._find_db_path() == db_path


def test_find_db_path_on_windows(monkeypatch, tmp_path) -> None:
    agent = ZCodeAgent()
    db_path = tmp_path / ".zcode" / "cli" / "db" / "db.sqlite"
    db_path.parent.mkdir(parents=True)
    db_path.touch()

    monkeypatch.setattr("agent_dump.agents.zcode.sys.platform", "win32")
    monkeypatch.setattr("agent_dump.agents.zcode.Path.home", lambda: tmp_path)

    assert agent._find_db_path() == db_path


def test_linux_has_no_default_zcode_root(monkeypatch, tmp_path) -> None:
    agent = ZCodeAgent()
    db_path = tmp_path / ".zcode" / "cli" / "db" / "db.sqlite"
    db_path.parent.mkdir(parents=True)
    db_path.touch()

    monkeypatch.setattr("agent_dump.agents.zcode.sys.platform", "linux")
    monkeypatch.setattr("agent_dump.agents.zcode.Path.home", lambda: tmp_path)

    assert agent.get_search_roots() == ()
    assert agent._find_db_path() is None


def test_get_sessions_and_export_from_zcode_db(tmp_path) -> None:
    agent = ZCodeAgent()
    db_path = tmp_path / "db.sqlite"
    now = _create_zcode_db(db_path)
    agent.db_path = db_path

    sessions = agent.get_sessions(days=3650)

    assert len(sessions) == 1
    session = sessions[0]
    assert session.id == "sess-zcode"
    assert session.title == "ZCode Session"
    assert session.created_at == datetime.fromtimestamp(now / 1000, tz=timezone.utc)
    assert session.source_path == db_path
    assert session.metadata["directory"] == "/workspace/zcode"
    assert session.metadata["model"] == "GLM-5.2"
    assert session.metadata["message_count"] == 2
    assert agent.get_session_uri(session) == "zcode://sess-zcode"

    session_data = agent.get_session_data(session)
    exported_text = json.dumps(session_data, ensure_ascii=False)
    assert "ZCode prompt" in exported_text
    assert "ZCode answer" in exported_text
    assert session_data["stats"]["message_count"] == 2
    assert session_data["stats"]["total_input_tokens"] == 12
    assert session_data["stats"]["total_output_tokens"] == 8

    head = agent.get_session_head(session)
    assert head["cwd_or_project"] == "/workspace/zcode"
    assert head["model"] == "GLM-5.2"
    assert head["message_count"] == 2
    assert head["subtargets"] == ["web/page.tsx"]

    json_path = agent.export_session(session, tmp_path / "json")
    raw_path = agent.export_raw_session(session, tmp_path / "raw")
    assert json_path.name == "sess-zcode.json"
    assert raw_path.name == "sess-zcode.raw.json"
