"""collect 模块测试。"""

from datetime import date, datetime, timedelta, timezone
import json
from unittest import mock

import pytest

from agent_dump.collect import (
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    SessionSummaryEntry,
    build_collect_final_prompt,
    build_collect_session_prompt,
    chunk_collect_events,
    collect_entries,
    empty_summary_payload,
    extract_collect_events,
    merge_summary_payloads,
    normalize_summary_payload,
    reduce_collect_summaries,
    request_structured_summary_from_llm,
    request_summary_from_llm,
    resolve_collect_date_range,
    summarize_collect_entries,
    write_collect_markdown,
)
from agent_dump.config import AIConfig


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

        entries, truncated = collect_entries(
            agents=[agent],
            since_date=(now - timedelta(days=2)).date(),
            until_date=now.date(),
            render_session_text_fn=lambda uri, data: f"# Session Dump\n{uri}\n{json.dumps(data)}",
        )

        assert len(entries) == 1
        assert entries[0].session_id == "s-in"
        assert entries[0].project_directory == "/repo/a"
        assert entries[0].events[0].kind == "user_intent"
        assert truncated is False
        assert entries[0].is_truncated is False

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

    def test_request_structured_summary_from_llm_parses_json_fence(self):
        with mock.patch("agent_dump.collect.request_summary_from_llm", return_value="```json\n{\"topics\":[\"A\"]}\n```"):
            result = request_structured_summary_from_llm(
                self._config(),
                "prompt",
                context_label="chunk-1",
            )

        assert result["topics"] == ["A"]

    def test_request_structured_summary_from_llm_retries_then_raises(self):
        with mock.patch("agent_dump.collect.request_summary_from_llm", return_value="not json"):
            with pytest.raises(RuntimeError, match="chunk-1"):
                request_structured_summary_from_llm(
                    self._config(),
                    "prompt",
                    context_label="chunk-1",
                )

    def test_build_collect_session_prompt_contains_required_sections(self):
        prompt = build_collect_session_prompt(self._entry(), source_truncated=False)

        assert "JSON 必须只包含这些字段" in prompt
        assert "session_uri: codex://s-1" in prompt
        assert "chunk: 1/1" in prompt

    def test_summarize_collect_entries_reports_progress_in_order(self):
        entry1 = self._entry(session_id="s-1")
        entry2 = self._entry(session_id="s-2")
        progress: list[tuple[int, int]] = []

        def _summary_side_effect(config, prompt, *, timeout_seconds=90):
            del config, timeout_seconds
            if "codex://s-1" in prompt:
                return '{"topics":["T1"],"key_actions":["A1"]}'
            return '{"topics":["T2"],"errors":["E2"]}'

        with mock.patch("agent_dump.collect.request_summary_from_llm", side_effect=_summary_side_effect):
            summaries = summarize_collect_entries(
                config=self._config(),
                entries=[entry1, entry2],
                summary_concurrency=2,
                progress_callback=lambda completed, total: progress.append((completed, total)),
            )

        assert [item.summary_data["topics"] for item in summaries] == [["T1"], ["T2"]]
        assert progress == [(1, 2), (2, 2)]

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

        responses = iter(
            [
                '{"topics":["T1"],"key_actions":["A1"]}',
                '{"topics":["T2"],"errors":["E2"]}',
                '{"topics":["T3"],"files":["/repo/a.py"]}',
            ]
        )

        with mock.patch("agent_dump.collect.request_summary_from_llm", side_effect=lambda *args, **kwargs: next(responses)):
            summaries = summarize_collect_entries(
                config=self._config(),
                entries=[entry],
                summary_concurrency=1,
            )

        assert summaries[0].chunk_count == 3
        assert summaries[0].summary_data["topics"] == ["T1", "T2", "T3"]
        assert summaries[0].summary_data["errors"] == ["E2"]

    def test_summarize_collect_entries_raises_wrapped_session_uri(self):
        with mock.patch("agent_dump.collect.request_summary_from_llm", return_value="bad json"):
            with pytest.raises(RuntimeError, match="codex://s-1"):
                summarize_collect_entries(
                    config=self._config(),
                    entries=[self._entry()],
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

        aggregate = reduce_collect_summaries(config=self._config(), session_summaries=summaries)

        assert aggregate.session_count == 17
        assert aggregate.reduction_depth >= 2
        assert "2026-03-05" in aggregate.date_summaries
        assert "/repo/0" in aggregate.project_summaries

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
