"""Collect summarization and reduction tests."""

from datetime import date, datetime, timezone
import json
from unittest import mock

import pytest

from agent_dump.collect import (
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    CollectLogger,
    CollectProgressEvent,
    MergeSessionsProgress,
    PlannedCollectEntry,
    SessionSummaryEntry,
    SummarizeChunksProgress,
    TreeReductionProgress,
    build_collect_final_prompt,
    build_collect_session_prompt,
    chunk_collect_events,
    reduce_collect_summaries,
    summarize_collect_entries,
)
from agent_dump.collect_summary import (
    normalize_summary_payload,
)
from agent_dump.config import MAX_COLLECT_SUMMARY_CONCURRENCY, AIConfig
from agent_dump.text_safety import has_unsafe_line_characters


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

    def test_build_collect_session_prompt_contains_required_sections(self):
        prompt = build_collect_session_prompt(self._entry(), source_truncated=False)

        assert "JSON 必须只包含这些字段" in prompt
        assert '"source": "codex://s-1#chunk-1/' in prompt
        assert "chunk: 1/1" in prompt

    def test_summarize_collect_entries_reports_progress_in_order(self):
        entry1 = self._planned_entry(session_id="s-1")
        entry2 = self._planned_entry(session_id="s-2")
        progress: list[CollectProgressEvent] = []

        def _summary_side_effect(config, prompt, *, timeout_seconds=90, **_kwargs):
            del config, timeout_seconds
            if "codex://s-1" in prompt:
                return '{"topics":["T1"],"key_actions":["A1"]}'
            return '{"topics":["T2"],"errors":["E2"]}'

        with mock.patch(
            "agent_dump.collect_requests.request_structured_summary_payload_from_llm", side_effect=_summary_side_effect
        ):
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[entry1, entry2],
                summary_concurrency=2,
                progress_callback=progress.append,
            )

        assert [item.summary_data["topics"] for item in summaries] == [["T1"], ["T2"]]
        summarize_events = [event for event in progress if isinstance(event, SummarizeChunksProgress)]
        merge_events = [event for event in progress if isinstance(event, MergeSessionsProgress)]
        assert summarize_events[0].current == 0
        assert summarize_events[-1].current == 2
        assert merge_events[0].current == 0
        assert merge_events[-1].current == 2

    def test_summarize_collect_entries_caps_runtime_concurrency(self):
        progress: list[CollectProgressEvent] = []

        with mock.patch(
            "agent_dump.collect_requests.request_structured_summary_payload_from_llm",
            return_value='{"topics":["T1"]}',
        ):
            summarize_collect_entries(
                config=self._config(),
                planned_entries=[self._planned_entry()],
                summary_concurrency=MAX_COLLECT_SUMMARY_CONCURRENCY + 1,
                progress_callback=progress.append,
            )

        summarize_events = [event for event in progress if isinstance(event, SummarizeChunksProgress)]
        assert summarize_events[0].concurrency == MAX_COLLECT_SUMMARY_CONCURRENCY

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
            "agent_dump.collect_requests.request_structured_summary_payload_from_llm",
            side_effect=lambda *args, **kwargs: next(responses),
        ) as request_summary:
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[planned_entry],
                summary_concurrency=1,
            )

        assert request_summary.call_count == 3
        assert summaries[0].summary_data["topics"] == ["T1", "T2", "T3"]
        assert summaries[0].summary_data["errors"] == ["E2"]

    def test_summarize_collect_entries_falls_back_when_session_merge_fails(self, tmp_path):
        entry = self._entry()
        event = CollectEvent(kind="assistant_key", role="assistant", text="event")
        planned_entry = PlannedCollectEntry(collect_entry=entry, chunks=((event,), (event,)))
        log_path = tmp_path / "collect.log"
        logger = CollectLogger(enabled=True, path=log_path, run_id="run-1")
        responses = iter(
            [
                '{"topics":["T1"],"key_actions":["A1"]}',
                '{"topics":["T2"],"key_actions":["A2"]}',
                "bad json",
                "bad json",
            ]
        )

        with (
            mock.patch("agent_dump.collect_reduction.SESSION_MERGE_LLM_THRESHOLD", 1),
            mock.patch(
                "agent_dump.collect_requests.request_structured_summary_payload_from_llm",
                side_effect=lambda *args, **kwargs: next(responses),
            ),
        ):
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[planned_entry],
                summary_concurrency=1,
                logger=logger,
            )

        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert summaries[0].summary_data["topics"] == ["T1", "T2"]
        assert summaries[0].summary_data["key_actions"] == ["A1", "A2"]
        assert records[-1]["event"] == "llm_merge_fallback"
        assert records[-1]["phase"] == "session_merge"

    def test_summarize_collect_entries_raises_wrapped_session_uri(self):
        with (
            mock.patch(
                "agent_dump.collect_requests.request_structured_summary_payload_from_llm", return_value="bad json"
            ),
            pytest.raises(RuntimeError, match="codex://s-1"),
        ):
            summarize_collect_entries(
                config=self._config(),
                planned_entries=[self._planned_entry()],
                summary_concurrency=1,
            )

    def test_summarize_collect_entries_skips_failed_session_and_keeps_others(self, tmp_path, capsys):
        """测试单个会话摘要失败时跳过该会话，其余会话正常返回"""
        entry_ok = self._planned_entry(session_id="s-ok")
        entry_bad = self._planned_entry(session_id="s-bad")
        log_path = tmp_path / "collect.log"
        logger = CollectLogger(enabled=True, path=log_path, run_id="run-1")

        def _summary_side_effect(config, prompt, *, timeout_seconds=90, **_kwargs):
            del config, timeout_seconds
            if "codex://s-bad" in prompt:
                return "bad json"
            return '{"topics":["T1"]}'

        with mock.patch(
            "agent_dump.collect_requests.request_structured_summary_payload_from_llm", side_effect=_summary_side_effect
        ):
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[entry_ok, entry_bad],
                summary_concurrency=1,
                logger=logger,
            )

        assert [item.collect_entry.session_id for item in summaries] == ["s-ok"]
        assert summaries[0].summary_data["topics"] == ["T1"]
        captured = capsys.readouterr()
        assert "codex://s-bad" in captured.err
        assert "1 个会话摘要失败" in captured.err
        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        failure_records = [record for record in records if record["event"] == "session_summary_failed"]
        assert len(failure_records) == 1
        assert failure_records[0]["session_uri"] == "codex://s-bad"

    def test_summarize_collect_entries_sanitizes_session_uri_and_remote_error(self, capsys):
        poison = "value\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        entry_ok = self._planned_entry(session_id="s-ok")
        entry_bad = self._planned_entry(session_id=f"s-bad-{poison}")

        def _summary_side_effect(config, prompt, *, timeout_seconds=90, **_kwargs):
            del config, timeout_seconds
            if "s-bad-" in prompt:
                raise RuntimeError(f"remote {poison}")
            return '{"topics":["T1"]}'

        with mock.patch(
            "agent_dump.collect_requests.request_structured_summary_payload_from_llm",
            side_effect=_summary_side_effect,
        ):
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[entry_ok, entry_bad],
                summary_concurrency=1,
            )

        assert [item.collect_entry.session_id for item in summaries] == ["s-ok"]
        lines = capsys.readouterr().err.splitlines()
        assert lines
        assert all(not has_unsafe_line_characters(line) for line in lines)
        assert "FORGED" in "\n".join(lines)

    def test_reduce_collect_summaries_tree_reduction(self):
        summaries = [
            SessionSummaryEntry(
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
        tree_events = [event for event in progress if isinstance(event, TreeReductionProgress)]
        assert tree_events[0].current == 0
        assert tree_events[-1].current == tree_events[-1].total

    def test_reduce_collect_summaries_falls_back_when_group_merge_fails(self, tmp_path):
        session_summaries = [
            SessionSummaryEntry(
                collect_entry=CollectEntry(
                    date_value=date(2026, 3, 5),
                    created_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
                    agent_name="codex",
                    agent_display_name="Codex",
                    session_id=f"s-{index}",
                    session_uri=f"codex://s-{index}",
                    session_title=f"task-{index}",
                    project_directory="/repo",
                    events=(CollectEvent(kind="user_intent", role="user", text="修复"),),
                    is_truncated=False,
                ),
                summary_data=normalize_summary_payload({"topics": [f"T{index}"]}),
            )
            for index in range(2)
        ]
        log_path = tmp_path / "collect.log"
        logger = CollectLogger(enabled=True, path=log_path, run_id="run-1")
        responses = iter(["bad json", "bad json"])

        with (
            mock.patch("agent_dump.collect_reduction.SESSION_MERGE_LLM_THRESHOLD", 1),
            mock.patch(
                "agent_dump.collect_requests.request_structured_summary_payload_from_llm",
                side_effect=lambda *args, **kwargs: next(responses),
            ),
        ):
            aggregate = reduce_collect_summaries(
                config=self._config(),
                session_summaries=session_summaries,
                group_size=2,
                logger=logger,
            )

        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert aggregate.summary_data["topics"] == ["T0", "T1"]
        assert records[-1]["event"] == "llm_merge_fallback"
        assert records[-1]["phase"] == "group_merge"

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
        envelopes = [json.loads(line) for line in prompt.splitlines() if line.startswith('{"untrusted_data"')]
        assert json.loads(envelopes[0]["content"])["topics"] == ["collect"]
        assert json.loads(envelopes[1]["content"])["bucket"] == "2026-03-05"
        assert json.loads(envelopes[2]["content"])["bucket"] == "/repo"
