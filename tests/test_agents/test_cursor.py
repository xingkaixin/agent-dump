"""
测试 agents/cursor.py 模块
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agent_dump.agents.cursor import CursorAgent


def _create_cursor_global_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


def _insert_kv(path: Path, key: str, value: dict) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO cursorDiskKV(key, value) VALUES (?, ?)",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


class TestCursorAgent:
    @staticmethod
    def _create_layout(monkeypatch, tmp_path):
        cursor_home = tmp_path / "home"
        monkeypatch.setattr("agent_dump.agents.cursor.Path.home", lambda: cursor_home)
        workspace_root = tmp_path / "workspaceStorage"
        global_db = cursor_home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        workspace_root.mkdir(parents=True)
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)
        monkeypatch.setenv("CURSOR_DATA_PATH", str(workspace_root))
        return workspace_root, global_db

    def test_is_available(self, monkeypatch, tmp_path):
        self._create_layout(monkeypatch, tmp_path)

        agent = CursorAgent()
        assert agent.is_available() is True

    def test_get_sessions_uses_request_id(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)

        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-1",
            {"composerId": "composer-1", "name": "Cursor Session", "createdAt": created_at_ms},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-1:b1",
            {"requestId": "request-1", "type": 1, "text": "hello"},
        )

        agent = CursorAgent()
        assert agent.is_available() is True
        sessions = agent.get_sessions(days=7)

        assert len(sessions) == 1
        assert sessions[0].id == "request-1"
        assert sessions[0].metadata["composer_id"] == "composer-1"
        assert agent.get_session_uri(sessions[0]) == "cursor://request-1"

    def test_get_session_data_extracts_messages_and_tool(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)

        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-2",
            {"composerId": "composer-2", "title": "Session 2", "createdAt": created_at_ms},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-2:b1",
            {
                "requestId": "request-2",
                "type": 1,
                "text": "user text",
                "timingInfo": {"clientRpcSendTime": created_at_ms},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-2:b2",
            {
                "type": 2,
                "text": "assistant text",
                "tokenCount": {"inputTokens": 10, "outputTokens": 20},
                "toolFormerData": {
                    "name": "subagent_call",
                    "params": {"message": "check"},
                    "status": "completed",
                    "result": {"ok": True},
                },
            },
        )

        agent = CursorAgent()
        sessions = agent.get_sessions(days=7)
        session = sessions[0]
        data = agent.get_session_data(session)

        assert data["id"] == "request-2"
        assert data["stats"]["message_count"] == 2
        assert data["stats"]["total_input_tokens"] == 10
        assert data["stats"]["total_output_tokens"] == 20
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
        tool_parts = [p for p in data["messages"][1]["parts"] if p.get("type") == "tool"]
        assert len(tool_parts) == 1
        assert tool_parts[0]["tool"] == "subagent"

    def test_export_raw_session_not_supported(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)

        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-3",
            {"composerId": "composer-3", "createdAt": created_at_ms},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-3:b1",
            {"requestId": "request-3", "type": 1, "text": "hello"},
        )

        agent = CursorAgent()
        session = agent.get_sessions(days=7)[0]
        try:
            agent.export_raw_session(session, tmp_path / "out")
            assert False, "expected NotImplementedError"
        except NotImplementedError:
            assert True

    def test_get_sessions_skips_null_composer_value(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)
        conn = sqlite3.connect(global_db)
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO cursorDiskKV(key, value) VALUES (?, ?)", ("composerData:null-one", None))
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        cur.execute(
            "INSERT OR REPLACE INTO cursorDiskKV(key, value) VALUES (?, ?)",
            (
                "composerData:ok-one",
                json.dumps({"composerId": "ok-one", "createdAt": now_ms, "name": "OK"}, ensure_ascii=False),
            ),
        )
        cur.execute(
            "INSERT OR REPLACE INTO cursorDiskKV(key, value) VALUES (?, ?)",
            (
                "bubbleId:ok-one:b1",
                json.dumps({"requestId": "request-ok", "type": 1, "text": "hello"}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

        agent = CursorAgent()
        sessions = agent.get_sessions(days=7)
        assert len(sessions) == 1
        assert sessions[0].id == "request-ok"
