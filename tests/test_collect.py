"""collect 模块测试。"""

from datetime import date, datetime, timedelta, timezone
import json
from unittest import mock

import pytest

from agent_dump.collect import (
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    CollectLogger,
    CollectProgressEvent,
    PlannedCollectEntry,
    SessionSummaryEntry,
    build_collect_final_prompt,
    build_collect_run_stats,
    build_collect_session_prompt,
    build_summary_json_schema,
    chunk_collect_events,
    collect_entries,
    empty_summary_payload,
    extract_collect_events,
    merge_summary_payloads,
    normalize_summary_payload,
    plan_collect_entries,
    reduce_collect_summaries,
    request_structured_summary_from_llm,
    request_structured_summary_payload_from_llm,
    request_summary_from_llm,
    resolve_collect_date_range,
    summarize_collect_entries,
    write_collect_markdown,
)
from agent_dump.config import AIConfig, CollectConfig


class TestCollectDates:
    def test_both_missing_defaults_today(self):
        today = date(2026, 3, 5)
        since, until = resolve_collect_date_range(None, None, today=today)
        assert since == today
        assert until == today

    def test_since_only_defaults_until_today(self):
        today = date(2026, 3, 5)
        since, until = resolve_collect_date_range("2026-03-01", None, today=today)
        assert since == date(2026, 3, 1)
        assert until == today

    def test_until_only_defaults_since_month_start(self):
        since, until = resolve_collect_date_range(None, "20260210", today=date(2026, 3, 5))
        assert since == date(2026, 2, 1)
        assert until == date(2026, 2, 10)

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            resolve_collect_date_range("2026-03-05", "2026-03-01")

    def test_defaults_today_in_local_timezone(self):
        local_tz = timezone(timedelta(hours=8))
        since, until = resolve_collect_date_range(None, None, local_tz=local_tz, today=None)
        assert since == until


class TestCollectExtraction:
    def test_extract_collect_events_keeps_high_signal_structures(self):
        session_data = {
            "messages": [
                {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "你好"},
                        {"type": "text", "text": "请修复 /repo/app.py 里的报错"},
                    ],
                },
                {
                    "role": "assistant",
                    "parts": [
                        {"type": "text", "text": "我决定先检查 app.py。"},
                        {"type": "tool", "tool": "read_file", "state": {"path": "/repo/app.py"}},
                        {"type": "text", "text": "```py\nprint('x')\n```"},
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "parts": [{"type": "text", "text": "Traceback: FileNotFoundError in /repo/app.py"}],
                },
            ]
        }

        events, truncated = extract_collect_events(session_data)

        assert truncated is False
        assert [event.kind for event in events] == [
            "user_intent",
            "decision",
            "tool_call",
            "code",
            "error",
        ]
        assert events[0].files == ("/repo/app.py",)
        assert events[2].tool_name == "read_file"

    def test_extract_collect_events_falls_back_when_empty(self):
        events, truncated = extract_collect_events({"messages": []}, fallback_text="fallback text")

        assert truncated is False
        assert len(events) == 1
        assert events[0].kind == "fallback"
        assert events[0].text == "fallback text"

    def test_extract_collect_events_respects_char_budget(self):
        session_data = {
            "messages": [
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "x" * 120}],
                },
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "text": "y" * 120}],
                },
            ]
        }

        events, truncated = extract_collect_events(session_data, char_budget=130)

        assert truncated is True
        assert len(events) == 1

    def test_chunk_collect_events_splits_long_event_sequences(self):
        events = [
            CollectEvent(kind="user_intent", role="user", text="a" * 1200),
            CollectEvent(kind="assistant_key", role="assistant", text="b" * 1200),
            CollectEvent(kind="decision", role="assistant", text="c" * 1200),
        ]

        chunks = chunk_collect_events(events, target_chars=1500)

        assert len(chunks) == 3
        assert all(chunks)

    def test_normalize_summary_payload_filters_unknown_and_dedupes(self):
        payload = normalize_summary_payload(
            {
                "topics": ["修复 collect", "修复 collect", ""],
                "errors": "timeout",
                "unknown": ["x"],
            }
        )

        assert payload["topics"] == ["修复 collect"]
        assert payload["errors"] == ["timeout"]
        assert set(payload) == {
            "topics",
            "decisions",
            "key_actions",
            "code_changes",
            "errors",
            "tools_used",
            "files",
            "artifacts",
            "open_questions",
            "notes",
        }

    def test_merge_summary_payloads_dedupes_per_field(self):
        merged = merge_summary_payloads(
            [
                {**empty_summary_payload(), "topics": ["A"], "errors": ["E1"]},
                {**empty_summary_payload(), "topics": ["A", "B"], "errors": ["E2"]},
            ]
        )

        assert merged["topics"] == ["A", "B"]
        assert merged["errors"] == ["E1", "E2"]


class TestCollectEntries:
    def test_collect_entries_filters_and_extracts(self):
        now = datetime.now(timezone.utc)
        in_range = mock.MagicMock()
        in_range.id = "s-in"
        in_range.title = "in"
        in_range.created_at = now - timedelta(days=1)
        in_range.updated_at = now - timedelta(days=1)
        in_range.metadata = {"cwd": "/repo/a"}

        out_range = mock.MagicMock()
        out_range.id = "s-out"
        out_range.title = "out"
        out_range.created_at = now - timedelta(days=40)
        out_range.updated_at = now - timedelta(days=40)
        out_range.metadata = {"cwd": "/repo/b"}

        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [in_range, out_range]
        agent.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        agent.get_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "修复 /repo/a.py 报错"}]}]
        }

        progress: list[CollectProgressEvent] = []
        entries, truncated = collect_entries(
            agents=[agent],
            since_date=(now - timedelta(days=2)).date(),
            until_date=now.date(),
            render_session_text_fn=lambda uri, data: f"# Session Dump\n{uri}\n{json.dumps(data)}",
            progress_callback=progress.append,
        )

        assert len(entries) == 1
        assert entries[0].session_id == "s-in"
        assert entries[0].project_directory == "/repo/a"
        assert entries[0].events[0].kind == "user_intent"
        assert truncated is False
        assert entries[0].is_truncated is False
        assert [event.stage for event in progress] == ["scan_sessions", "scan_sessions"]
        assert progress[-1].current == 1
        assert progress[-1].total == 1

    def test_collect_entries_ignores_denied_agent_projects(self):
        now = datetime.now(timezone.utc)
        denied_root = mock.MagicMock()
        denied_root.id = "s-denied-root"
        denied_root.title = "denied-root"
        denied_root.created_at = now - timedelta(hours=1)
        denied_root.updated_at = now - timedelta(hours=1)
        denied_root.metadata = {"cwd": "/repo/fin-agent/agent"}

        denied_child = mock.MagicMock()
        denied_child.id = "s-denied-child"
        denied_child.title = "denied-child"
        denied_child.created_at = now - timedelta(hours=2)
        denied_child.updated_at = now - timedelta(hours=2)
        denied_child.metadata = {"cwd": "/repo/fin-agent/agent/subdir"}

        allowed = mock.MagicMock()
        allowed.id = "s-allowed"
        allowed.title = "allowed"
        allowed.created_at = now - timedelta(hours=3)
        allowed.updated_at = now - timedelta(hours=3)
        allowed.metadata = {"cwd": "/repo/other"}

        claude_agent = mock.MagicMock()
        claude_agent.name = "claudecode"
        claude_agent.display_name = "Claude Code"
        claude_agent.get_sessions.return_value = [denied_root, denied_child, allowed]
        claude_agent.get_session_uri.side_effect = lambda s: f"claude://{s.id}"
        claude_agent.get_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "处理仓库问题"}]}]
        }

        codex_session = mock.MagicMock()
        codex_session.id = "s-codex"
        codex_session.title = "codex"
        codex_session.created_at = now - timedelta(hours=4)
        codex_session.updated_at = now - timedelta(hours=4)
        codex_session.metadata = {"cwd": "/repo/fin-agent/agent"}

        codex_agent = mock.MagicMock()
        codex_agent.name = "codex"
        codex_agent.display_name = "Codex"
        codex_agent.get_sessions.return_value = [codex_session]
        codex_agent.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        codex_agent.get_session_data.return_value = {
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "处理 codex 会话"}]}]
        }

        entries, truncated = collect_entries(
            agents=[claude_agent, codex_agent],
            since_date=(now - timedelta(days=1)).date(),
            until_date=now.date(),
            collect_config=CollectConfig(agent_denies={"claudecode": ("/repo/fin-agent/agent",)}),
            render_session_text_fn=lambda uri, data: f"# Session Dump\n{uri}\n{json.dumps(data)}",
        )

        assert truncated is False
        assert [entry.session_id for entry in entries] == ["s-codex", "s-allowed"]
        assert [entry.agent_name for entry in entries] == ["codex", "claudecode"]

    def test_collect_entries_filters_by_user_local_date(self):
        local_tz = timezone(timedelta(hours=8))
        utc_time = datetime(2026, 3, 4, 18, 0, tzinfo=timezone.utc)
        session = mock.MagicMock()
        session.id = "cross-day"
        session.title = "cross-day"
        session.created_at = utc_time
        session.updated_at = utc_time
        session.metadata = {"cwd": "/repo/cross-day"}

        agent = mock.MagicMock()
        agent.name = "opencode"
        agent.display_name = "OpenCode"
        agent.get_sessions.return_value = [session]
        agent.get_session_uri.return_value = "opencode://cross-day"
        agent.get_session_data.return_value = {"messages": [{"role": "user", "parts": [{"type": "text", "text": "修复"}]}]}

        entries, truncated = collect_entries(
            agents=[agent],
            since_date=date(2026, 3, 5),
            until_date=date(2026, 3, 5),
            render_session_text_fn=lambda uri, data: f"# Session Dump\n{uri}\n",
            local_tz=local_tz,
        )

        assert truncated is False
        assert len(entries) == 1
        assert entries[0].date_value == date(2026, 3, 5)
        assert entries[0].session_id == "cross-day"

    def test_plan_collect_entries_reports_chunk_totals(self):
        entries = [
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
                agent_name="codex",
                agent_display_name="Codex",
                session_id="s-1",
                session_uri="codex://s-1",
                session_title="task-1",
                project_directory="/repo",
                events=(
                    CollectEvent(kind="user_intent", role="user", text="a" * 1800),
                    CollectEvent(kind="assistant_key", role="assistant", text="b" * 1800),
                ),
                is_truncated=False,
            ),
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 3, 0, 0, tzinfo=timezone.utc),
                agent_name="codex",
                agent_display_name="Codex",
                session_id="s-2",
                session_uri="codex://s-2",
                session_title="task-2",
                project_directory="/repo",
                events=(CollectEvent(kind="user_intent", role="user", text="c" * 100),),
                is_truncated=False,
            ),
        ]
        progress: list[CollectProgressEvent] = []

        planned, chunk_count = plan_collect_entries(entries, progress_callback=progress.append)

        assert len(planned) == 2
        assert chunk_count == 3
        assert sum(len(item.chunks) for item in planned) == 3
        assert [event.stage for event in progress] == ["plan_chunks", "plan_chunks", "plan_chunks"]
        assert progress[-1].chunk_total == 3

    def test_build_collect_run_stats_counts_agents_and_chunks(self):
        entries = [
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
                agent_name="codex",
                agent_display_name="Codex",
                session_id="s-1",
                session_uri="codex://s-1",
                session_title="task-1",
                project_directory="/repo",
                events=(CollectEvent(kind="user_intent", role="user", text="a" * 1800),),
                is_truncated=False,
            ),
            CollectEntry(
                date_value=date(2026, 3, 5),
                created_at=datetime(2026, 3, 5, 3, 0, 0, tzinfo=timezone.utc),
                agent_name="claudecode",
                agent_display_name="Claude Code",
                session_id="s-2",
                session_uri="claude://s-2",
                session_title="task-2",
                project_directory="/repo",
                events=(
                    CollectEvent(kind="user_intent", role="user", text="b" * 1800),
                    CollectEvent(kind="assistant_key", role="assistant", text="c" * 1800),
                ),
                is_truncated=False,
            ),
        ]
        planned_entries, _ = plan_collect_entries(entries)

        stats = build_collect_run_stats(
            entries=entries,
            planned_entries=planned_entries,
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            summary_concurrency=4,
        )

        assert stats.since == "2026-03-01"
        assert stats.until == "2026-03-05"
        assert stats.agent_session_counts == {"Codex": 1, "Claude Code": 1}
        assert stats.session_count == 2
        assert stats.chunk_count == 3
        assert stats.concurrency == 4


class TestCollectStructuredSummary:
    def _config(self) -> AIConfig:
        return AIConfig(
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key="sk-test",
        )

    def _entry(self, *, text: str = "修复 collect", session_id: str = "s-1") -> CollectEntry:
        return CollectEntry(
            date_value=date(2026, 3, 5),
            created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
            agent_name="codex",
            agent_display_name="Codex",
            session_id=session_id,
            session_uri=f"codex://{session_id}",
            session_title="task",
            project_directory="/repo",
            events=(CollectEvent(kind="user_intent", role="user", text=text),),
            is_truncated=False,
        )

    def _planned_entry(self, *, text: str = "修复 collect", session_id: str = "s-1") -> PlannedCollectEntry:
        entry = self._entry(text=text, session_id=session_id)
        return PlannedCollectEntry(collect_entry=entry, chunks=tuple(chunk_collect_events(entry.events)))

    def test_request_structured_summary_from_llm_parses_json_fence(self):
        with mock.patch(
            "agent_dump.collect.request_structured_summary_payload_from_llm",
            return_value="```json\n{\"topics\":[\"A\"]}\n```",
        ):
            result = request_structured_summary_from_llm(
                self._config(),
                "prompt",
                context_label="chunk-1",
            )

        assert result["topics"] == ["A"]

    def test_request_structured_summary_from_llm_retries_then_raises(self):
        with mock.patch("agent_dump.collect.request_structured_summary_payload_from_llm", return_value="not json"):
            with pytest.raises(RuntimeError, match="chunk-1"):
                request_structured_summary_from_llm(
                    self._config(),
                    "prompt",
                    context_label="chunk-1",
                )

    def test_request_structured_summary_payload_openai_uses_json_schema(self):
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"choices": [{"message": {"content": '{"topics":["A"]}'}}]}).encode(
            "utf-8"
        )
        response.__enter__.return_value = response
        response.__exit__.return_value = None

        with mock.patch("urllib.request.urlopen", return_value=response) as mock_urlopen:
            result = request_structured_summary_payload_from_llm(self._config(), "prompt")

        assert result == '{"topics":["A"]}'
        body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"] == build_summary_json_schema()

    def test_request_structured_summary_from_llm_logs_parse_error(self, tmp_path):
        log_path = tmp_path / "collect.log"
        logger = CollectLogger(enabled=True, path=log_path, run_id="run-1")

        with mock.patch("agent_dump.collect.request_structured_summary_payload_from_llm", return_value="not json"):
            with pytest.raises(RuntimeError, match="chunk-1"):
                request_structured_summary_from_llm(
                    self._config(),
                    "prompt",
                    context_label="chunk-1",
                    logger=logger,
                    phase="chunk_summary",
                    session_uri="codex://s-1",
                    chunk_index=1,
                    chunk_total=2,
                )

        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert [record["event"] for record in records] == ["llm_request", "llm_response", "llm_parse_error", "llm_request", "llm_response", "llm_parse_error"]
        assert records[-1]["session_uri"] == "codex://s-1"
        assert records[-1]["phase"] == "chunk_summary"
        assert records[-1]["response_preview"] == "not json"

    def test_request_structured_summary_from_llm_retries_request_error(self, tmp_path):
        log_path = tmp_path / "collect.log"
        logger = CollectLogger(enabled=True, path=log_path, run_id="run-1")
        responses = iter([RuntimeError("The read operation timed out"), '{"topics":["A"]}'])

        def _side_effect(*args, **kwargs):
            result = next(responses)
            if isinstance(result, Exception):
                raise result
            return result

        with mock.patch("agent_dump.collect.request_structured_summary_payload_from_llm", side_effect=_side_effect):
            result = request_structured_summary_from_llm(
                self._config(),
                "prompt",
                context_label="chunk-1",
                logger=logger,
            )

        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert result["topics"] == ["A"]
        assert [record["event"] for record in records] == ["llm_request", "llm_request_error", "llm_request", "llm_response"]

    def test_build_collect_session_prompt_contains_required_sections(self):
        prompt = build_collect_session_prompt(self._entry(), source_truncated=False)

        assert "JSON 必须只包含这些字段" in prompt
        assert "session_uri: codex://s-1" in prompt
        assert "chunk: 1/1" in prompt

    def test_summarize_collect_entries_reports_progress_in_order(self):
        entry1 = self._planned_entry(session_id="s-1")
        entry2 = self._planned_entry(session_id="s-2")
        progress: list[CollectProgressEvent] = []

        def _summary_side_effect(config, prompt, *, timeout_seconds=90):
            del config, timeout_seconds
            if "codex://s-1" in prompt:
                return '{"topics":["T1"],"key_actions":["A1"]}'
            return '{"topics":["T2"],"errors":["E2"]}'

        with mock.patch("agent_dump.collect.request_structured_summary_payload_from_llm", side_effect=_summary_side_effect):
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[entry1, entry2],
                summary_concurrency=2,
                progress_callback=progress.append,
            )

        assert [item.summary_data["topics"] for item in summaries] == [["T1"], ["T2"]]
        summarize_events = [event for event in progress if event.stage == "summarize_chunks"]
        merge_events = [event for event in progress if event.stage == "merge_sessions"]
        assert summarize_events[0].current == 0
        assert summarize_events[-1].current == 2
        assert merge_events[0].current == 0
        assert merge_events[-1].current == 2

    def test_summarize_collect_entries_splits_long_session_into_multiple_chunks(self):
        events = tuple(
            CollectEvent(kind="assistant_key", role="assistant", text=f"event-{index}-{'x' * 1800}")
            for index in range(3)
        )
        entry = CollectEntry(
            date_value=date(2026, 3, 5),
            created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
            agent_name="codex",
            agent_display_name="Codex",
            session_id="long",
            session_uri="codex://long",
            session_title="long",
            project_directory="/repo",
            events=events,
            is_truncated=False,
        )
        planned_entry = PlannedCollectEntry(collect_entry=entry, chunks=tuple(chunk_collect_events(entry.events)))

        responses = iter(
            [
                '{"topics":["T1"],"key_actions":["A1"]}',
                '{"topics":["T2"],"errors":["E2"]}',
                '{"topics":["T3"],"files":["/repo/a.py"]}',
            ]
        )

        with mock.patch(
            "agent_dump.collect.request_structured_summary_payload_from_llm",
            side_effect=lambda *args, **kwargs: next(responses),
        ):
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[planned_entry],
                summary_concurrency=1,
            )

        assert summaries[0].chunk_count == 3
        assert summaries[0].summary_data["topics"] == ["T1", "T2", "T3"]
        assert summaries[0].summary_data["errors"] == ["E2"]

    def test_summarize_collect_entries_raises_wrapped_session_uri(self):
        with mock.patch("agent_dump.collect.request_structured_summary_payload_from_llm", return_value="bad json"):
            with pytest.raises(RuntimeError, match="codex://s-1"):
                summarize_collect_entries(
                    config=self._config(),
                    planned_entries=[self._planned_entry()],
                    summary_concurrency=1,
                )

    def test_reduce_collect_summaries_tree_reduction(self):
        summaries = [
            SessionSummaryEntry(
                index=index,
                collect_entry=CollectEntry(
                    date_value=date(2026, 3, 5 + index % 2),
                    created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
                    agent_name="codex",
                    agent_display_name="Codex",
                    session_id=f"s-{index}",
                    session_uri=f"codex://s-{index}",
                    session_title=f"task-{index}",
                    project_directory=f"/repo/{index % 3}",
                    events=(CollectEvent(kind="user_intent", role="user", text="修复"),),
                    is_truncated=False,
                ),
                summary_data=normalize_summary_payload({"topics": [f"T{index}"], "key_actions": [f"A{index}"]}),
                chunk_count=1,
                source_truncated=False,
            )
            for index in range(17)
        ]

        progress: list[CollectProgressEvent] = []
        aggregate = reduce_collect_summaries(
            config=self._config(),
            session_summaries=summaries,
            progress_callback=progress.append,
        )

        assert aggregate.session_count == 17
        assert aggregate.reduction_depth >= 2
        assert "2026-03-05" in aggregate.date_summaries
        assert "/repo/0" in aggregate.project_summaries
        tree_events = [event for event in progress if event.stage == "tree_reduction"]
        assert tree_events[0].current == 0
        assert tree_events[-1].current == tree_events[-1].total

    def test_build_collect_final_prompt_contains_required_sections(self):
        aggregate = CollectAggregate(
            summary_data=normalize_summary_payload({"topics": ["collect"], "errors": ["timeout"]}),
            date_summaries={"2026-03-05": ["task: 修复 collect"]},
            project_summaries={"/repo": ["task: 修复 collect"]},
            session_count=1,
            reduction_depth=0,
        )

        prompt = build_collect_final_prompt(
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            aggregate=aggregate,
            has_truncated=False,
        )

        assert "# 时段工作总结（2026-03-01 ~ 2026-03-05）" in prompt
        assert "## 按日期" in prompt
        assert "## 按项目/目录" in prompt
        assert "## 重点事项（决策/风险/阻塞）" in prompt
        assert '"topics": [' in prompt
        assert "### 2026-03-05" in prompt
        assert "### /repo" in prompt


class TestCollectLLM:
    def test_request_summary_openai_success(self):
        config = AIConfig(
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key="sk-test",
        )
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "# summary",
                    }
                }
            ]
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = None

        with mock.patch("urllib.request.urlopen", return_value=response):
            result = request_summary_from_llm(config, "prompt")

        assert result == "# summary"

    def test_request_summary_api_error(self):
        config = AIConfig(
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-7-sonnet",
            api_key="ak-test",
        )
        with mock.patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                request_summary_from_llm(config, "prompt")


class TestCollectOutput:
    def test_write_collect_markdown_uses_date_range_filename(self, tmp_path):
        path = write_collect_markdown(
            "# report",
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            output_dir=tmp_path,
        )
        assert path == tmp_path / "agent-dump-collect-20260301-20260305.md"
        assert path.read_text(encoding="utf-8") == "# report"

    def test_write_collect_markdown_uses_explicit_output_path(self, tmp_path):
        output_path = tmp_path / "reports" / "report.md"
        path = write_collect_markdown(
            "# report",
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            output_path=output_path,
        )
        assert path == output_path
        assert path.read_text(encoding="utf-8") == "# report"

    def test_write_collect_markdown_creates_parent_dirs_for_output_path(self, tmp_path):
        output_path = tmp_path / "nested" / "collect" / "report.md"
        path = write_collect_markdown(
            "# report",
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            output_path=output_path,
        )
        assert path == output_path
        assert output_path.parent.is_dir()

    def test_write_collect_markdown_rejects_both_output_dir_and_output_path(self, tmp_path):
        with pytest.raises(ValueError, match="mutually exclusive"):
            write_collect_markdown(
                "# report",
                since_date=date(2026, 3, 1),
                until_date=date(2026, 3, 5),
                output_dir=tmp_path,
                output_path=tmp_path / "report.md",
            )
