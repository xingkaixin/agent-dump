"""
测试 agents/cursor.py 模块
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from unittest import mock

from message_test_support import require_tool_part
import pytest

from agent_dump.agents.base import Session
from agent_dump.agents.cursor import _BUBBLE_RANGE_BATCH_SIZE, CursorAgent, _key_prefix_bounds
from agent_dump.agents.cursor_storage import _METADATA_BUBBLE_SCAN_LIMIT, CursorStoreReader, parse_cursor_json


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


def _insert_raw_kv(path: Path, key: str, value: object) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO cursorDiskKV(key, value) VALUES (?, ?)", (key, value))
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
        monkeypatch.setattr("agent_dump.agents.cursor_storage.Path.home", lambda: cursor_home)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)
        return global_db

    def test_is_available(self, monkeypatch, tmp_path):
        self._create_layout(monkeypatch, tmp_path)

        agent = CursorAgent()
        assert agent.is_available() is True

    def test_get_sessions_uses_request_id(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)

        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-1",
            {
                "composerId": "composer-1",
                "name": "Cursor Session",
                "createdAt": created_at_ms,
                "modelConfig": {"modelName": "composer-2-fast"},
            },
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
        assert sessions[0].metadata["model"] == "composer-2-fast"
        assert sessions[0].metadata["message_count"] == 1
        assert agent.get_session_uri(sessions[0]) == "cursor://request-1"

    def test_get_sessions_query_count_is_bounded_by_batch_count(self, monkeypatch, tmp_path):
        """AD-124：bubble 摘要按批读取，查询数不再随每个会话增长。"""
        global_db = self._create_layout(monkeypatch, tmp_path)

        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

        def _seed(count: int) -> None:
            for index in range(count):
                composer_id = f"composer-{index}"
                _insert_kv(
                    global_db,
                    f"composerData:{composer_id}",
                    {"composerId": composer_id, "createdAt": created_at_ms, "name": f"Session {index}"},
                )
                for bubble in range(3):
                    _insert_kv(
                        global_db,
                        f"bubbleId:{composer_id}:b{bubble}",
                        {
                            "requestId": f"request-{index}",
                            "type": 1 if bubble % 2 == 0 else 2,
                            "text": "hello",
                            "modelInfo": {"modelName": "composer-2"},
                        },
                    )

        def _count_statements(agent: CursorAgent) -> tuple[int, list[Session]]:
            statements: list[str] = []
            original_reader = agent._store.reader

            @contextmanager
            def counting_reader():
                with original_reader() as reader:
                    reader._connection.set_trace_callback(statements.append)
                    try:
                        yield reader
                    finally:
                        reader._connection.set_trace_callback(None)

            # patch 打在实例上，两次测量各用一个新实例，无需 undo
            # （undo 会连 _create_layout 的 Path.home / 环境变量 patch 一起撤掉）
            monkeypatch.setattr(agent._store, "reader", counting_reader)
            sessions = agent.get_sessions(days=7)
            return len(statements), sessions

        _seed(2)
        agent = CursorAgent()
        assert agent.is_available() is True
        two_count, two_sessions = _count_statements(agent)

        assert {session.id for session in two_sessions} == {"request-0", "request-1"}
        assert two_sessions[0].metadata["message_count"] == 3
        assert two_sessions[0].metadata["model"] == "composer-2"

        _seed(8)
        agent = CursorAgent()
        assert agent.is_available() is True
        eight_count, eight_sessions = _count_statements(agent)

        assert len(eight_sessions) == 8
        assert two_count == eight_count == 3, (
            f"查询数应与会话数无关，2 个会话用了 {two_count} 条、8 个会话用了 {eight_count} 条"
        )

        over_one_batch = _BUBBLE_RANGE_BATCH_SIZE + 1
        _seed(over_one_batch)
        agent = CursorAgent()
        assert agent.is_available() is True
        batched_count, batched_sessions = _count_statements(agent)

        assert len(batched_sessions) == over_one_batch
        assert batched_count == 5, "composer 一次读取，消息计数与元数据摘要各按两批读取"

    def test_metadata_scan_is_bounded_to_the_first_bubbles(self, monkeypatch, tmp_path):
        """AD-124：列表元数据只扫会话开头若干条 bubble，不再搬运整段正文。

        这是一处刻意的语义收窄：修复前 requestId/model 会扫完全部 bubble。
        """
        global_db = self._create_layout(monkeypatch, tmp_path)
        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-0",
            {"composerId": "composer-0", "createdAt": created_at_ms, "name": "Session"},
        )
        # 前 LIMIT 条都不带 modelInfo，只有远超上限的那条带
        total = _METADATA_BUBBLE_SCAN_LIMIT + 5
        for bubble in range(total):
            payload: dict[str, object] = {"requestId": "request-0", "type": 1, "text": "hello"}
            if bubble == total - 1:
                payload["modelInfo"] = {"modelName": "late-model"}
            _insert_kv(global_db, f"bubbleId:composer-0:b{bubble:04d}", payload)

        agent = CursorAgent()
        assert agent.is_available() is True
        sessions = agent.get_sessions(days=7)

        assert sessions[0].id == "request-0", "开头就有的 requestId 仍然拿得到"
        assert sessions[0].metadata["model"] is None, "超出扫描上限的 model 不再被拾取"
        assert sessions[0].metadata["message_count"] == total, "计数走 SQL 聚合，仍覆盖全部 bubble"

    def test_get_sessions_falls_back_when_json1_is_unavailable(self, monkeypatch, tmp_path):
        """老 SQLite 缺 JSON1 时退回逐会话解析，元数据结果必须一致。"""
        global_db = self._create_layout(monkeypatch, tmp_path)
        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-0",
            {"composerId": "composer-0", "createdAt": created_at_ms, "name": "Session"},
        )
        for bubble in range(3):
            _insert_kv(
                global_db,
                f"bubbleId:composer-0:b{bubble}",
                {
                    "requestId": "request-0",
                    "type": 1 if bubble % 2 == 0 else 2,
                    "text": "hello",
                    "modelInfo": {"modelName": "composer-2"},
                },
            )

        agent = CursorAgent()
        assert agent.is_available() is True
        aggregated = agent.get_sessions(days=7)

        monkeypatch.setattr(CursorStoreReader, "_count_messages", lambda self, composer_ids: None)
        fallback = agent.get_sessions(days=7)

        assert [s.id for s in fallback] == [s.id for s in aggregated]
        assert fallback[0].metadata["message_count"] == aggregated[0].metadata["message_count"] == 3
        assert fallback[0].metadata["model"] == aggregated[0].metadata["model"] == "composer-2"

    def test_get_session_data_extracts_messages_and_tool(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)

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

    def test_get_session_head_extracts_model_message_count_and_subtargets(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)

        created_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-head",
            {
                "composerId": "composer-head",
                "title": "Head Session",
                "createdAt": created_at_ms,
                "modelConfig": {"modelName": "claude-4.6"},
                "subagentComposerIds": ["worker-1", "worker-2"],
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-head:b1",
            {"requestId": "request-head", "type": 1, "text": "hello"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-head:b2",
            {"type": 2, "text": "world", "modelInfo": {"modelName": "claude-4.6"}},
        )

        agent = CursorAgent()
        session = agent.find_session_by_request_id("request-head")
        assert session is not None

        with mock.patch.object(agent._store, "reader", side_effect=AssertionError("unexpected query")):
            head = agent.get_session_head(session)

        assert head["model"] == "claude-4.6"
        assert head["message_count"] == 2
        assert head["message_count_completeness"] == "exact"
        assert head["subtargets"] == ["worker-1", "worker-2"]

    def test_export_raw_session_not_supported(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)

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
            raise AssertionError("expected NotImplementedError")
        except NotImplementedError:
            assert True

    def test_get_sessions_skips_null_composer_value(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
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
        global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-order",
            {"composerId": "composer-order", "createdAt": now_ms, "name": "Ordered"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-order:b-2",
            {
                "requestId": "request-order",
                "type": 2,
                "text": "second",
                "timingInfo": {"clientRpcSendTime": now_ms + 20},
            },
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
        global_db = self._create_layout(monkeypatch, tmp_path)
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

    def test_find_session_by_request_id_treats_wildcards_as_literals(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        request_id = "literal%_id"
        _insert_kv(
            global_db,
            "composerData:target",
            {"composerId": "target", "createdAt": now_ms, "name": "Target"},
        )
        _insert_kv(
            global_db,
            "bubbleId:target:b1",
            {"requestId": request_id, "type": 1, "text": "target"},
        )
        for index in range(50):
            _insert_kv(
                global_db,
                f"bubbleId:noise-{index}:b1",
                {"requestId": f"literal-noise-{index}Xid", "type": 1, "text": "noise"},
            )

        agent = CursorAgent()
        original_query = CursorStoreReader._query
        candidate_counts: list[int] = []

        def recording_query(reader, sql, params):
            rows = original_query(reader, sql, params)
            if "instr(value" in sql:
                candidate_counts.append(len(rows))
            return rows

        monkeypatch.setattr(CursorStoreReader, "_query", recording_query)
        matched = agent.find_session_by_request_id(request_id)

        assert matched is not None
        assert matched.id == request_id
        assert candidate_counts == [1]

    def test_key_prefix_bounds_covers_exactly_prefix_matches(self):
        """测试范围边界与 LIKE 前缀匹配语义一致"""
        lower, upper = _key_prefix_bounds("bubbleId:abc:")

        assert lower == "bubbleId:abc:"
        assert upper == "bubbleId:abc;"
        assert lower <= "bubbleId:abc:b1" < upper
        assert not (lower <= "bubbleId:abcd:x" < upper)
        assert not (lower <= "composerData:abc" < upper)

    def test_get_sessions_unparseable_created_at_is_not_treated_as_now(self, monkeypatch, tmp_path):
        """测试 createdAt 无法解析时不再伪装成当前时间混入结果"""
        global_db = self._create_layout(monkeypatch, tmp_path)
        _insert_kv(
            global_db,
            "composerData:composer-bad-time",
            {"composerId": "composer-bad-time", "createdAt": "not-a-timestamp", "name": "Bad Time"},
        )

        agent = CursorAgent()

        assert agent.get_sessions(days=7) == []

    def test_get_sessions_falls_back_to_updated_at_when_created_at_invalid(self, monkeypatch, tmp_path):
        """测试 createdAt 非法但 updatedAt 有效时用 updatedAt 兜底"""
        global_db = self._create_layout(monkeypatch, tmp_path)
        updated_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-updated-only",
            {
                "composerId": "composer-updated-only",
                "createdAt": "not-a-timestamp",
                "updatedAt": updated_ms,
                "name": "Updated Only",
            },
        )

        agent = CursorAgent()
        sessions = agent.get_sessions(days=7)

        assert len(sessions) == 1
        assert sessions[0].created_at == sessions[0].updated_at
        assert int(sessions[0].created_at.timestamp() * 1000) == updated_ms

    def test_find_session_by_id_resolves_request_id_and_composer_fallback(self, monkeypatch, tmp_path):
        """测试 find_session_by_id 优先按 request id 定位，无 bubble 时回退全量扫描"""
        global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-with-req",
            {"composerId": "composer-with-req", "createdAt": now_ms, "name": "With Request"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-with-req:b1",
            {"requestId": "request-fast", "type": 1, "text": "hello"},
        )
        _insert_kv(
            global_db,
            "composerData:composer-empty",
            {"composerId": "composer-empty", "createdAt": now_ms, "name": "No Bubbles"},
        )

        agent = CursorAgent()

        by_request = agent.find_session_by_id("request-fast")
        assert by_request is not None
        assert by_request.id == "request-fast"

        by_composer = agent.find_session_by_id("composer-empty")
        assert by_composer is not None
        assert by_composer.id == "composer-empty"

        assert agent.find_session_by_id("missing") is None

    def test_get_session_data_converts_create_plan_to_plan_part(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
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
            part["tool"] for message in data["messages"] for part in message["parts"] if part.get("type") == "tool"
        ]
        assert "create_plan" not in tool_names

    def test_get_session_data_backfills_subagent_output(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
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
                "modelConfig": {"modelName": "composer-2-fast"},
                "subagentInfo": {"parentComposerId": "composer-parent", "subagentTypeName": "explore"},
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
            "bubbleId:subagent-composer:c-empty",
            {
                "type": 2,
                "text": "\n\n\n",
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
        with mock.patch.object(
            agent._store,
            "transcript_bubbles",
            wraps=agent._store.transcript_bubbles,
        ) as read_bubbles:
            data = agent.get_session_data(session)

        child_bubble_reads = [call for call in read_bubbles.call_args_list if call.args[0] == "subagent-composer"]
        assert len(child_bubble_reads) == 1

        tool_message = next(message for message in data["messages"] if message["role"] == "tool")
        tool_part = tool_message["parts"][0]
        assert tool_message["time_created"] == now_ms + 1
        assert tool_part["subagent_id"] == "subagent-composer"
        assert tool_part["subagent_type"] == "explore"
        assert tool_part["state"]["prompt"] == "Read the files and summarize."
        assert tool_part["state"]["model"] == "composer-2-fast"
        assert tool_part["state"]["output"] is None

        completion_message = next(
            message
            for message in data["messages"]
            if message["role"] == "assistant" and message.get("subagent_id") == "subagent-composer"
        )
        assert completion_message["time_created"] == now_ms + 3
        assert completion_message["model"] == "composer-2-fast"
        assert completion_message["subagent_type"] == "explore"
        assert completion_message["parts"] == [
            {"type": "text", "text": "Subagent summary output", "time_created": now_ms + 3}
        ]

    def test_get_session_data_skips_empty_assistant_bubble(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-empty",
            {"composerId": "composer-empty", "createdAt": now_ms, "name": "Empty Session"},
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-empty:b1",
            {
                "requestId": "request-empty",
                "type": 1,
                "text": "hello",
                "timingInfo": {"clientRpcSendTime": now_ms},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-empty:b2",
            {
                "type": 2,
                "text": "\n\n\n",
                "timingInfo": {"clientRpcSendTime": now_ms + 1},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-empty:b3",
            {
                "type": 2,
                "text": "assistant reply",
                "timingInfo": {"clientRpcSendTime": now_ms + 2},
            },
        )

        agent = CursorAgent()
        session = next(item for item in agent.get_sessions(days=7) if item.id == "request-empty")
        data = agent.get_session_data(session)

        texts = [
            part["text"] for message in data["messages"] for part in message["parts"] if part.get("type") == "text"
        ]
        assert texts == ["hello", "assistant reply"]
        assert "[empty message]" not in texts

    def test_get_session_data_inherits_model_from_user_turn(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
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

    def test_parse_helpers_cover_cursor_edge_shapes(self):
        agent = CursorAgent()
        decoder = agent._transcript_decoder

        assert parse_cursor_json(b'{"ok": true}') == {"ok": True}
        assert parse_cursor_json(b"\xff") is None
        assert parse_cursor_json(1) is None
        assert parse_cursor_json(" ") is None
        assert parse_cursor_json("{") is None
        assert parse_cursor_json("[]") is None

        assert agent._extract_title({"title": "Title Fallback"}, "composer-abc") == "Title Fallback"
        assert agent._extract_title({}, "composer-abc") == "Cursor Session composer"

        assert agent._parse_datetime_utc("1741140000000") == datetime(2025, 3, 5, 2, 0, tzinfo=timezone.utc)
        assert agent._parse_datetime_utc("1741140000") == datetime(2025, 3, 5, 2, 0, tzinfo=timezone.utc)
        assert agent._parse_datetime_utc("bad") is None
        assert agent._parse_datetime_utc(None) is None

        fallback_ms = 100
        assert decoder._extract_timestamp({"createdAt": "2026-01-01T00:00:00Z"}, fallback_ms) == 1767225600000
        assert (
            decoder._extract_timestamp({"createdAt": "bad", "timingInfo": {"clientSettleTime": "123.0"}}, fallback_ms)
            == 123
        )
        assert decoder._extract_timestamp({"timingInfo": {"clientRpcSendTime": "bad"}}, fallback_ms) == fallback_ms

        assert decoder._extract_text_content({"codeBlocks": [{"content": "code"}]}, "user") == "code"
        assert decoder._extract_text_content({"thinking": {"text": "thought"}}, "assistant") == "thought"
        assert decoder._extract_text_content({"finalText": "done"}, "assistant") == "done"

        assert decoder._extract_subagent_prompt({"description": "Explore"}) == "Explore"
        assert decoder._extract_subagent_prompt("raw prompt") == "raw prompt"
        assert decoder._extract_subagent_prompt(["prompt"]) == json.dumps(["prompt"], ensure_ascii=False, indent=2)
        assert decoder._extract_subagent_type("raw") is None

        assert decoder._build_plan_part({"params": "raw"}, 1) is None
        assert decoder._build_plan_part({"params": json.dumps({"other": "value"})}, 1) is None
        plan = decoder._build_plan_part(
            {
                "params": json.dumps({"plan": "  plan body  "}, ensure_ascii=False),
                "result": json.dumps({"rejected": {"reason": "no"}}, ensure_ascii=False),
                "additionalData": {"reviewData": {"selectedOption": "approve"}},
            },
            123,
        )
        assert plan == {
            "type": "plan",
            "input": "plan body",
            "output": '{"reason": "no"}',
            "approval_status": "success",
            "time_created": 123,
        }

        assert decoder._extract_tool_output_parts([{"type": "text", "text": " output ", "time_created": 4}], 1) == [
            {"type": "text", "text": "output", "time_created": 4}
        ]
        assert decoder._extract_tool_output_parts("raw output", 5) == [
            {"type": "text", "text": "raw output", "time_created": 5}
        ]
        assert decoder._extract_tool_output_parts(None, 5) == []

        assert decoder._extract_tokens({"usage": {"input_tokens": 2, "output_tokens": 3}}) == (2, 3)
        assert decoder._extract_tokens({"contextWindowStatusAtCreation": {"tokensUsed": 9}}) == (9, 0)

        tool_part, completion = decoder._extract_tool_part(
            {
                "toolFormerData": {
                    "name": "read_file_v2",
                    "callId": "call-1",
                    "rawArgs": '{"targetFile":',
                    "result": {"stderr": "boom"},
                    "additionalData": {"status": "failed"},
                }
            },
            10,
        )
        assert completion is None
        assert tool_part is not None
        normalized_tool_part = require_tool_part(tool_part)
        assert normalized_tool_part["callID"] == "call-1"
        assert normalized_tool_part["state"]["status"] == "failed"
        assert normalized_tool_part["state"]["arguments"] == {"_raw": '{"targetFile":'}
        assert normalized_tool_part["state"]["error"] == "boom"

    def test_get_session_data_attaches_tool_to_parent_and_exports_usage(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-parent-tool",
            {
                "composerId": "composer-parent-tool",
                "createdAt": now_ms,
                "name": "Parent Tool",
                "usageData": {
                    "contextTokensUsed": 1000,
                    "contextTokenLimit": 2000,
                    "contextUsagePercent": 50,
                },
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-parent-tool:b1",
            {
                "requestId": "request-parent-tool",
                "type": 1,
                "text": "inspect file",
                "usage": {"input_tokens": 3, "output_tokens": 4},
                "timingInfo": {"clientRpcSendTime": now_ms},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-parent-tool:b2",
            {
                "type": 2,
                "parentBubbleId": "b1",
                "contextWindowStatusAtCreation": {"tokensUsed": 12},
                "timingInfo": {"clientRpcSendTime": now_ms + 1},
                "toolFormerData": {
                    "name": "read_file_v2",
                    "toolCallId": "tool-parent",
                    "params": {"targetFile": "/workspace/a.py"},
                    "status": "completed",
                    "result": "file body",
                },
            },
        )

        agent = CursorAgent()
        session = next(item for item in agent.get_sessions(days=7) if item.id == "request-parent-tool")
        data = agent.get_session_data(session)

        assert len(data["messages"]) == 1
        message = data["messages"][0]
        assert [part["type"] for part in message["parts"]] == ["text", "tool"]
        assert message["parts"][1]["callID"] == "tool-parent"
        assert message["parts"][1]["state"]["output"] == "file body"
        assert data["stats"]["total_input_tokens"] == 15
        assert data["stats"]["total_output_tokens"] == 4
        assert data["stats"]["context_tokens_used"] == 1000
        assert data["stats"]["context_token_limit"] == 2000
        assert data["stats"]["context_usage_percent"] == 50

    def test_get_session_data_keeps_corrupted_and_alternate_text_shapes(self, monkeypatch, tmp_path):
        global_db = self._create_layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-shapes",
            {"composerId": "composer-shapes", "createdAt": now_ms, "name": "Shapes"},
        )
        _insert_raw_kv(global_db, "bubbleId:composer-shapes:b1", "{")
        _insert_kv(
            global_db,
            "bubbleId:composer-shapes:b2",
            {
                "requestId": "request-shapes",
                "type": 2,
                "codeBlocks": [{"content": "code block"}],
                "timingInfo": {"clientRpcSendTime": now_ms + 1},
            },
        )
        _insert_kv(
            global_db,
            "bubbleId:composer-shapes:b3",
            {
                "type": 2,
                "thinking": {"text": "thinking text"},
                "timingInfo": {"clientRpcSendTime": now_ms + 2},
            },
        )

        agent = CursorAgent()
        session = next(item for item in agent.get_sessions(days=7) if item.id == "request-shapes")
        data = agent.get_session_data(session)
        head = agent.get_session_head(session)

        texts = [part["text"] for message in data["messages"] for part in message["parts"] if part["type"] == "text"]
        assert texts == ["[corrupted message]", "code block", "thinking text"]
        assert head["message_count"] == 2

    def test_find_session_by_request_id_none_paths(self, monkeypatch, tmp_path):
        cursor_home = tmp_path / "empty-home"
        monkeypatch.setattr("agent_dump.agents.cursor_storage.Path.home", lambda: cursor_home)

        empty_agent = CursorAgent()
        assert empty_agent.scan() == []
        assert empty_agent.find_session_by_request_id("missing") is None

        global_db = self._create_layout(monkeypatch, tmp_path)
        _insert_kv(
            global_db,
            "bubbleId:orphan-composer:b1",
            {"requestId": "orphan-request", "type": 1, "text": "orphan"},
        )

        agent = CursorAgent()
        assert agent.find_session_by_request_id("missing") is None
        assert agent.find_session_by_request_id("orphan-request") is None

        _insert_raw_kv(global_db, "composerData:orphan-composer", "[]")
        assert agent.find_session_by_request_id("orphan-request") is None


class TestMalformedNumericFieldsInBubbles:
    """AD-122：bubble 里的非数字 token 计数不得让 cursor provider 抛异常。"""

    def test_non_numeric_token_counts_degrade_to_zero(self):
        decoder = CursorAgent()._transcript_decoder

        assert decoder._extract_tokens({"tokenCount": {"inputTokens": "abc", "outputTokens": None}}) == (0, 0)
        assert decoder._extract_tokens({"usage": {"input_tokens": [], "output_tokens": {}}}) == (0, 0)
        assert decoder._extract_tokens({"contextWindowStatusAtCreation": {"tokensUsed": "x"}}) == (0, 0)

    def test_usable_token_counts_are_preserved(self):
        decoder = CursorAgent()._transcript_decoder

        assert decoder._extract_tokens({"tokenCount": {"inputTokens": 12, "outputTokens": 34}}) == (12, 34)
        assert decoder._extract_tokens({"tokenCount": {"inputTokens": "12", "outputTokens": "34"}}) == (12, 34)

    def test_out_of_range_composer_timestamp_yields_none(self):
        agent = CursorAgent()

        assert agent._parse_datetime_utc(1e30) is None

    def test_second_and_millisecond_timestamps_both_parse(self):
        """Cursor 同一字段两种单位共存，阈值 1e12 秒（约公元 33658 年）以上判为毫秒。"""
        agent = CursorAgent()
        expected = datetime(2024, 1, 1, tzinfo=timezone.utc)

        assert agent._parse_datetime_utc(1704067200) == expected
        assert agent._parse_datetime_utc(1704067200000) == expected

    @pytest.mark.parametrize(
        "value",
        [10**400, -(10**400), float("nan"), float("inf"), float("-inf"), "1e1000000"],
    )
    def test_unrepresentable_timestamps_use_existing_fallbacks(self, value):
        agent = CursorAgent()

        assert agent._parse_datetime_utc(value) is None
        assert agent._transcript_decoder._extract_timestamp({"timingInfo": {"clientRpcSendTime": value}}, 123) == 123


def _subagent_tool_bubble(target_composer_id: str, timestamp_ms: int, tool_call_id: str) -> dict:
    """构造一个指向 target_composer_id 的 subagent tool bubble。"""
    return {
        "type": 2,
        "timingInfo": {"clientRpcSendTime": timestamp_ms},
        "toolFormerData": {
            "name": "task_v2",
            "status": "completed",
            "toolCallId": tool_call_id,
            "params": json.dumps({"description": "d", "prompt": "p", "subagentType": "explore"}),
            "result": json.dumps({"agentId": target_composer_id}),
            "additionalData": {"status": "success", "subagentComposerId": target_composer_id},
        },
    }


class TestSubagentExpansionIsBounded:
    """AD-123：subagentComposerId 来自不可信存储，展开必须有环检测与去重。"""

    @staticmethod
    def _layout(monkeypatch, tmp_path):
        cursor_home = tmp_path / "home"
        monkeypatch.setattr("agent_dump.agents.cursor_storage.Path.home", lambda: cursor_home)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)
        return global_db

    def test_mutually_referencing_composers_do_not_recurse_forever(self, monkeypatch, tmp_path):
        """A 引用 B、B 又引用 A：修复前是 RecursionError。"""
        global_db = self._layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

        for name, other in (("composer-a", "composer-b"), ("composer-b", "composer-a")):
            _insert_kv(global_db, f"composerData:{name}", {"composerId": name, "createdAt": now_ms, "name": name})
            _insert_kv(
                global_db,
                f"bubbleId:{name}:t1",
                _subagent_tool_bubble(other, now_ms + 1, f"tool-{name}"),
            )

        agent = CursorAgent()
        agent.is_available()
        session = agent._build_session_from_composer(
            composer_id="composer-a",
            request_id="composer-a",
            composer={"composerId": "composer-a", "createdAt": now_ms, "name": "composer-a"},
        )

        data = agent.get_session_data(session)

        assert isinstance(data, dict)
        assert data["id"] == "composer-a"

    def test_self_referencing_composer_is_not_expanded(self, monkeypatch, tmp_path):
        global_db = self._layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:loop",
            {"composerId": "loop", "createdAt": now_ms, "name": "loop"},
        )
        _insert_kv(global_db, "bubbleId:loop:t1", _subagent_tool_bubble("loop", now_ms + 1, "tool-loop"))

        agent = CursorAgent()
        agent.is_available()
        session = agent._build_session_from_composer(
            composer_id="loop",
            request_id="loop",
            composer={"composerId": "loop", "createdAt": now_ms, "name": "loop"},
        )

        data = agent.get_session_data(session)

        assert isinstance(data, dict)

    def test_repeated_reference_to_one_subagent_is_parsed_once(self, monkeypatch, tmp_path):
        """同一次调用里两个 tool part 指向同一个 subagent，只应展开一次。"""
        global_db = self._layout(monkeypatch, tmp_path)
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:parent",
            {"composerId": "parent", "createdAt": now_ms, "name": "parent"},
        )
        for i in (1, 2):
            _insert_kv(
                global_db,
                f"bubbleId:parent:t{i}",
                _subagent_tool_bubble("worker", now_ms + i, f"tool-{i}"),
            )
        _insert_kv(
            global_db,
            "composerData:worker",
            {"composerId": "worker", "createdAt": now_ms, "name": "worker"},
        )
        _insert_kv(
            global_db,
            "bubbleId:worker:c1",
            {"type": 2, "text": "worker output", "timingInfo": {"clientRpcSendTime": now_ms}},
        )

        agent = CursorAgent()
        agent.is_available()
        session = agent._build_session_from_composer(
            composer_id="parent",
            request_id="parent",
            composer={"composerId": "parent", "createdAt": now_ms, "name": "parent"},
        )

        expansions: list[str] = []
        decoder = agent._transcript_decoder
        original = decoder._expand_subagent
        monkeypatch.setattr(
            decoder,
            "_expand_subagent",
            lambda composer_id, **kwargs: (expansions.append(composer_id), original(composer_id, **kwargs))[1],
        )

        agent.get_session_data(session)

        assert expansions == ["worker"], "重复引用同一 subagent 必须命中 memo"


class TestDiscoveryDependsOnlyOnGlobalStore:
    """AD-156：可用性只由真正被读取的 state.vscdb 决定，且与调用顺序无关。"""

    @staticmethod
    def _home_without_store(monkeypatch, tmp_path) -> Path:
        cursor_home = tmp_path / "home"
        cursor_home.mkdir()
        monkeypatch.setattr("agent_dump.agents.cursor_storage.Path.home", lambda: cursor_home)
        return cursor_home

    @staticmethod
    def _write_one_session(global_db: Path) -> None:
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:composer-1",
            {"composerId": "composer-1", "name": "Only Global", "createdAt": now_ms, "lastUpdatedAt": now_ms},
        )
        _insert_kv(global_db, "bubbleId:composer-1:b1", {"type": 1, "text": "hi", "requestId": "req-1"})

    def test_global_store_alone_is_enough(self, monkeypatch, tmp_path):
        cursor_home = self._home_without_store(monkeypatch, tmp_path)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)
        self._write_one_session(global_db)

        assert CursorAgent().is_available() is True
        # 每个入口都用全新实例：可用性不得依赖同一实例上先跑过 is_available()
        assert len(CursorAgent().get_sessions(days=7)) == 1
        assert len(CursorAgent().scan()) == 1
        assert CursorAgent().find_session_by_request_id("req-1") is not None

    def test_workspace_storage_alone_is_not_enough(self, monkeypatch, tmp_path):
        self._home_without_store(monkeypatch, tmp_path)
        (tmp_path / "workspaceStorage").mkdir()

        agent = CursorAgent()
        assert agent.is_available() is False
        assert agent.get_sessions(days=7) == []

    def test_neither_source_present(self, monkeypatch, tmp_path):
        self._home_without_store(monkeypatch, tmp_path)

        agent = CursorAgent()
        assert agent.is_available() is False
        assert agent.scan() == []
        assert agent.find_session_by_request_id("req-1") is None

    def test_availability_check_does_not_change_read_results(self, monkeypatch, tmp_path):
        cursor_home = self._home_without_store(monkeypatch, tmp_path)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)
        self._write_one_session(global_db)

        fresh = CursorAgent()
        primed = CursorAgent()
        primed.is_available()

        assert [s.id for s in fresh.get_sessions(days=7)] == [s.id for s in primed.get_sessions(days=7)]

    def test_unreadable_store_is_not_reported_available(self, monkeypatch, tmp_path):
        """存在但打不开的文件不能被报告为可用，否则 Scanner 会在更深处才失败。"""
        cursor_home = self._home_without_store(monkeypatch, tmp_path)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        global_db.write_bytes(b"")

        def refuse(*args, **kwargs):
            raise sqlite3.OperationalError("unable to open database file")

        monkeypatch.setattr("agent_dump.agents.cursor_storage.sqlite3.connect", refuse)
        assert CursorAgent().is_available() is False

    def test_search_roots_only_list_the_store_that_is_read(self, monkeypatch, tmp_path):
        self._home_without_store(monkeypatch, tmp_path)

        rendered = [root.render() for root in CursorAgent().get_search_roots()]
        assert len(rendered) == 1
        assert "state.vscdb" in rendered[0]
        assert not any("workspaceStorage" in line for line in rendered)


class TestDaysWindowAppliesBeforeBubbleAggregation:
    """AD-157：days 窗口必须先于 bubble 聚合生效。"""

    @staticmethod
    def _layout_with_history(monkeypatch, tmp_path, *, old_bubbles: int) -> Path:
        cursor_home = tmp_path / "home"
        monkeypatch.setattr("agent_dump.agents.cursor_storage.Path.home", lambda: cursor_home)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)

        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        old_ms = int((datetime.now(tz=timezone.utc) - timedelta(days=400)).timestamp() * 1000)
        _insert_kv(
            global_db,
            "composerData:recent",
            {"composerId": "recent", "name": "Recent", "createdAt": now_ms, "lastUpdatedAt": now_ms},
        )
        for i in range(4):
            _insert_kv(
                global_db,
                f"bubbleId:recent:{i:06d}",
                {"type": 1, "text": "hi", "requestId": "req-recent", "modelInfo": {"modelName": "gpt-5"}},
            )
        _insert_kv(
            global_db,
            "composerData:ancient",
            {"composerId": "ancient", "name": "Ancient", "createdAt": old_ms, "lastUpdatedAt": old_ms},
        )
        conn = sqlite3.connect(global_db)
        conn.executemany(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            [
                (f"bubbleId:ancient:{i:08d}", json.dumps({"type": 1, "text": "x" * 100, "requestId": f"r{i}"}))
                for i in range(old_bubbles)
            ],
        )
        conn.commit()
        conn.close()
        return global_db

    @staticmethod
    def _count_scanned_rows(agent: CursorAgent, days: int) -> tuple[int, list[Session]]:
        """统计 SQLite 实际访问的行数，比墙钟时间更稳定地反映扫描规模。"""
        scanned = [0]
        real_reader = agent._store.reader

        @contextmanager
        def counting_reader():
            with real_reader() as reader:
                reader._connection.set_progress_handler(lambda: scanned.__setitem__(0, scanned[0] + 1) or 0, 100)
                yield reader

        object.__setattr__(agent._store, "reader", counting_reader)
        sessions = agent.get_sessions(days=days)
        return scanned[0], sessions

    def test_short_window_does_not_scan_excluded_history(self, monkeypatch, tmp_path):
        self._layout_with_history(monkeypatch, tmp_path, old_bubbles=4000)

        narrow_cost, narrow = self._count_scanned_rows(CursorAgent(), days=1)
        wide_cost, wide = self._count_scanned_rows(CursorAgent(), days=3650)

        assert [s.id for s in narrow] == ["req-recent"]
        assert len(wide) == 2
        assert narrow_cost * 5 < wide_cost, (
            f"days=1 的代价（{narrow_cost}）应远低于全历史（{wide_cost}），否则窗口外的 bubble 仍被扫描"
        )

    def test_metadata_is_unchanged_by_the_window(self, monkeypatch, tmp_path):
        self._layout_with_history(monkeypatch, tmp_path, old_bubbles=200)

        recent = next(s for s in CursorAgent().get_sessions(days=1) if s.id == "req-recent")
        from_full_scan = next(s for s in CursorAgent().get_sessions(days=3650) if s.id == "req-recent")

        assert recent.metadata["message_count"] == from_full_scan.metadata["message_count"] == 4
        assert recent.metadata["model"] == from_full_scan.metadata["model"] == "gpt-5"
        assert recent.title == from_full_scan.title

    def test_fallback_path_agrees_with_the_aggregate_path(self, monkeypatch, tmp_path):
        self._layout_with_history(monkeypatch, tmp_path, old_bubbles=50)

        aggregated = CursorAgent().get_sessions(days=3650)
        monkeypatch.setattr(CursorStoreReader, "_count_messages", lambda self, composer_ids: None)
        fallback = CursorAgent().get_sessions(days=3650)

        assert [s.id for s in fallback] == [s.id for s in aggregated]
        assert [s.metadata["message_count"] for s in fallback] == [s.metadata["message_count"] for s in aggregated]
        assert [s.metadata["model"] for s in fallback] == [s.metadata["model"] for s in aggregated]

    def test_more_composers_than_one_batch_are_all_counted(self, monkeypatch, tmp_path):
        """composer 数超过单条 SQL 的批上限时不得漏计。"""
        cursor_home = tmp_path / "home"
        monkeypatch.setattr("agent_dump.agents.cursor_storage.Path.home", lambda: cursor_home)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)

        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        total = _BUBBLE_RANGE_BATCH_SIZE * 2 + 3
        conn = sqlite3.connect(global_db)
        for i in range(total):
            conn.execute(
                "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
                (
                    f"composerData:c{i:04d}",
                    json.dumps({"composerId": f"c{i:04d}", "name": f"S{i}", "createdAt": now_ms}),
                ),
            )
            conn.execute(
                "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
                (
                    f"bubbleId:c{i:04d}:b0",
                    json.dumps({"type": 1, "text": "hi", "requestId": f"req-{i:04d}"}),
                ),
            )
        conn.commit()
        conn.close()

        sessions = CursorAgent().get_sessions(days=7)

        assert len(sessions) == total
        assert all(s.metadata["message_count"] == 1 for s in sessions)


class TestNaiveIsoIsInterpretedAsUtc:
    """AD-158：无 offset 的 Cursor ISO 时间在所有主机上按 UTC 解释。"""

    NAIVE = "2026-01-01T00:00:00"
    NAIVE_EPOCH_MS = 1767225600000

    @pytest.mark.parametrize("tz_name", ["UTC", "Asia/Shanghai", "America/New_York"])
    def test_session_and_bubble_agree_across_host_timezones(self, monkeypatch, tz_name):
        monkeypatch.setenv("TZ", tz_name)
        time.tzset()

        agent = CursorAgent()
        parsed = agent._parse_datetime_utc(self.NAIVE)

        assert parsed is not None
        assert parsed.isoformat() == "2026-01-01T00:00:00+00:00"
        # Session 与 bubble 必须落在同一个瞬间，否则消息时间相对会话时间会整体漂移
        assert int(parsed.timestamp() * 1000) == self.NAIVE_EPOCH_MS
        assert agent._transcript_decoder._extract_timestamp({"createdAt": self.NAIVE}, 0) == self.NAIVE_EPOCH_MS

    @pytest.mark.parametrize("tz_name", ["UTC", "Asia/Shanghai"])
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00+00:00"),
            ("2026-01-01T00:00:00+08:00", "2025-12-31T16:00:00+00:00"),
            ("2026-01-01T00:00:00-05:00", "2026-01-01T05:00:00+00:00"),
            (1767225600, "2026-01-01T00:00:00+00:00"),
            (1767225600000, "2026-01-01T00:00:00+00:00"),
        ],
    )
    def test_explicit_offsets_and_epochs_are_unchanged(self, monkeypatch, tz_name, raw, expected):
        monkeypatch.setenv("TZ", tz_name)
        time.tzset()

        parsed = CursorAgent()._parse_datetime_utc(raw)

        assert parsed is not None
        assert parsed.isoformat() == expected

    @pytest.mark.parametrize("tz_name", ["UTC", "Asia/Shanghai"])
    def test_days_boundary_does_not_drop_sessions_by_host_timezone(self, monkeypatch, tmp_path, tz_name):
        """naive 时间按本地时区解释时，边界附近的 Session 会因主机时区被漏掉。"""
        monkeypatch.setenv("TZ", tz_name)
        time.tzset()

        cursor_home = tmp_path / "home"
        monkeypatch.setattr("agent_dump.agents.cursor_storage.Path.home", lambda: cursor_home)
        global_db = TestCursorAgent._cursor_user_root(cursor_home) / "globalStorage" / "state.vscdb"
        global_db.parent.mkdir(parents=True)
        _create_cursor_global_db(global_db)

        # 落在窗口内但距离 cutoff 不到一个时区偏移，本地时区解释会把它推到窗口外
        created = datetime.now(tz=timezone.utc) - timedelta(days=1) + timedelta(hours=2)
        _insert_kv(
            global_db,
            "composerData:edge",
            {"composerId": "edge", "name": "Edge", "createdAt": created.replace(tzinfo=None).isoformat()},
        )
        _insert_kv(global_db, "bubbleId:edge:b0", {"type": 1, "text": "hi", "requestId": "req-edge"})

        assert [s.id for s in CursorAgent().get_sessions(days=1)] == ["req-edge"]
