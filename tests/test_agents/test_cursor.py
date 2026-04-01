"""
测试 agents/cursor.py 模块
"""

import json
import os
import sqlite3
import sys
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
    def _cursor_user_root(cursor_home: Path) -> Path:
        if os.name == "nt":
            return cursor_home / "AppData" / "Roaming" / "Cursor" / "User"
        if sys.platform.startswith("darwin"):
            return cursor_home / "Library" / "Application Support" / "Cursor" / "User"
        return cursor_home / ".config" / "Cursor" / "User"

    @staticmethod
    def _create_layout(monkeypatch, tmp_path):
        cursor_home = tmp_path / "home"
        monkeypatch.setattr("agent_dump.agents.cursor.Path.home", lambda: cursor_home)
        workspace_root = tmp_path / "workspaceStorage"
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
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
        assert data["stats"]["message_count"] == 3
        assert data["stats"]["total_input_tokens"] == 10
        assert data["stats"]["total_output_tokens"] == 20
        assert data["messages"][0]["role"] == "user"
        assistant_messages = [m for m in data["messages"] if m["role"] == "assistant"]
        tool_messages = [m for m in data["messages"] if m["role"] == "tool"]
        assert len(assistant_messages) == 1
        assert len(tool_messages) == 1
        assert tool_messages[0]["parts"][0]["tool"] == "subagent"

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

    def test_get_session_data_sorts_by_created_time(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-order",
            {"composerId": "composer-order", "createdAt": now_ms, "name": "Ordered"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-order:b-2",
            {"requestId": "request-order", "type": 2, "text": "second", "timingInfo": {"clientRpcSendTime": now_ms + 20}},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-order:b-1",
            {"type": 1, "text": "first", "timingInfo": {"clientRpcSendTime": now_ms + 10}},
        )

        agent = CursorAgent()
        session = next(item for item in agent.get_sessions(days=7) if item.id == "request-order")
        data = agent.get_session_data(session)
        assert data["messages"][0]["parts"][0]["text"] == "first"
        assert data["messages"][1]["parts"][0]["text"] == "second"

    def test_find_session_by_request_id_supports_non_anchor_request(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-any-req",
            {"composerId": "composer-any-req", "createdAt": now_ms, "name": "Any Request"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-any-req:b1",
            {"requestId": "request-anchor", "type": 1, "text": "hello"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-any-req:b2",
            {"requestId": "request-other", "type": 2, "text": "world"},
        )

        agent = CursorAgent()
        matched = agent.find_session_by_request_id("request-other")
        assert matched is not None
        assert matched.id == "request-other"
        assert matched.metadata["composer_id"] == "composer-any-req"

    def test_get_session_data_converts_create_plan_to_plan_part(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-plan",
            {"composerId": "composer-plan", "createdAt": now_ms, "name": "Plan Session"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-plan:b1",
            {
                "requestId": "request-plan",
                "type": 1,
                "text": "please plan",
                "modelInfo": {"modelName": "default"},
                "timingInfo": {"clientRpcSendTime": now_ms},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-plan:b2",
            {
                "type": 2,
                "timingInfo": {"clientRpcSendTime": now_ms + 1},
                "toolFormerData": {
                    "name": "create_plan",
                    "status": "completed",
                    "params": json.dumps({"plan": "# Plan Title\n\n- first"}, ensure_ascii=False),
                    "result": json.dumps({"rejected": {}}, ensure_ascii=False),
                    "additionalData": {
                        "reviewData": {
                            "status": "Requested",
                            "selectedOption": "none",
                            "isShowingInput": False,
                        }
                    },
                },
            },
        )

        agent = CursorAgent()
        session = next(item for item in agent.get_sessions(days=7) if item.id == "request-plan")
        data = agent.get_session_data(session)

        plan_messages = [
            message for message in data["messages"] if any(part.get("type") == "plan" for part in message["parts"])
        ]
        assert len(plan_messages) == 1
        plan_part = next(part for part in plan_messages[0]["parts"] if part.get("type") == "plan")
        assert plan_part["input"] == "# Plan Title\n\n- first"
        assert plan_part["approval_status"] == "fail"
        assert plan_part["output"] is None
        tool_names = [
            part["tool"]
            for message in data["messages"]
            for part in message["parts"]
            if part.get("type") == "tool"
        ]
        assert "create_plan" not in tool_names

    def test_get_session_data_backfills_subagent_output(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-parent",
            {"composerId": "composer-parent", "createdAt": now_ms, "name": "Parent Session"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-parent:b1",
            {
                "requestId": "request-parent",
                "type": 1,
                "text": "run subagent",
                "modelInfo": {"modelName": "default"},
                "timingInfo": {"clientRpcSendTime": now_ms},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-parent:b2",
            {
                "type": 2,
                "timingInfo": {"clientRpcSendTime": now_ms + 1},
                "toolFormerData": {
                    "name": "task_v2",
                    "status": "completed",
                    "toolCallId": "tool-1",
                    "params": json.dumps(
                        {
                            "description": "Explore code",
                            "prompt": "Read the files and summarize.",
                            "subagentType": "explore",
                        },
                        ensure_ascii=False,
                    ),
                    "result": json.dumps({"agentId": "subagent-composer"}, ensure_ascii=False),
                    "additionalData": {
                        "status": "success",
                        "subagentComposerId": "subagent-composer",
                    },
                },
            },
        )
        _insert_kv(
            global_db,
            "composerData:subagent-composer",
            {
                "composerId": "subagent-composer",
                "createdAt": now_ms + 2,
                "name": "Child Session",
                "subagentInfo": {"parentComposerId": "composer-parent"},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:subagent-composer:c1",
            {
                "requestId": "child-request",
                "type": 1,
                "text": "Read the files and summarize.",
                "timingInfo": {"clientRpcSendTime": now_ms + 2},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:subagent-composer:c2",
            {
                "type": 2,
                "text": "Subagent summary output",
                "timingInfo": {"clientRpcSendTime": now_ms + 3},
            },
        )

        agent = CursorAgent()
        session = next(item for item in agent.get_sessions(days=7) if item.id == "request-parent")
        data = agent.get_session_data(session)

        tool_part = next(
            part
            for message in data["messages"]
            for part in message["parts"]
            if part.get("type") == "tool" and part.get("tool") == "subagent"
        )
        assert tool_part["subagent_id"] == "subagent-composer"
        assert tool_part["state"]["prompt"] == "Read the files and summarize."
        assert tool_part["state"]["output"] == [
            {
                "type": "text",
                "text": "Subagent summary output",
                "time_created": now_ms + 3,
            }
        ]

    def test_get_session_data_inherits_model_from_user_turn(self, monkeypatch, tmp_path):
        _, global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-model",
            {"composerId": "composer-model", "createdAt": now_ms, "name": "Model Session"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-model:b1",
            {
                "requestId": "request-model",
                "type": 1,
                "text": "fix it",
                "modelInfo": {"modelName": "claude-4.6-opus-high-thinking"},
                "timingInfo": {"clientRpcSendTime": now_ms},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-model:b2",
            {
                "type": 2,
                "text": "assistant reply",
                "timingInfo": {"clientRpcSendTime": now_ms + 1},
                "toolFormerData": {
                    "name": "read_file_v2",
                    "status": "completed",
                    "params": json.dumps({"targetFile": "/tmp/a.py"}, ensure_ascii=False),
                },
            },
        )

        agent = CursorAgent()
        session = agent.get_sessions(days=7)[0]
        data = agent.get_session_data(session)

        assert data["messages"][0]["model"] == "claude-4.6-opus-high-thinking"
        assert data["messages"][1]["model"] == "claude-4.6-opus-high-thinking"
        tool_message = next(message for message in data["messages"] if message["role"] == "tool")
        assert tool_message["model"] == "claude-4.6-opus-high-thinking"
