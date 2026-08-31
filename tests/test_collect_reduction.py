"""Collect summarization and reduction tests."""

from dataclasses import replace
from datetime import date, datetime, timezone
import json
from unittest import mock

from locale_helpers import Keys, expect
import pytest

from agent_dump.collect_events import chunk_collect_events
from agent_dump.collect_logging import CollectLogger
from agent_dump.collect_models import (
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    CollectMode,
    CollectProgressEvent,
    CollectSummaryGroup,
    MergeSessionsProgress,
    PlannedCollectEntry,
    SessionSummaryEntry,
    StructuredSummaryPhase,
    SummarizeChunksProgress,
    TreeReductionProgress,
)
from agent_dump.collect_prompts import (
    FINAL_PROMPT_CHAR_BUDGET,
    build_collect_final_prompt,
    build_collect_session_prompt,
)
from agent_dump.collect_reduction import (
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

    @pytest.mark.parametrize("merge_fails", [False, True])
    def test_reduction_preserves_all_inputs_until_compression(self, merge_fails: bool) -> None:
        evidence = [f"evidence-{index:02d}" for index in range(17)]
        summaries = [
            SessionSummaryEntry(
                self._entry(session_id=f"s-{index}"),
                normalize_summary_payload({"key_actions": [value]}),
            )
            for index, value in enumerate(evidence)
        ]
        compressed = normalize_summary_payload({"key_actions": ["all facts compressed"]})
        with mock.patch(
            "agent_dump.collect_reduction.request_structured_summary_from_llm",
            side_effect=RuntimeError("unavailable") if merge_fails else None,
            return_value=compressed,
        ) as request:
            aggregate = reduce_collect_summaries(
                config=self._config(),
                session_summaries=summaries,
                request_structured_summary=request,
            )

        assert request.call_count == 1
        assert all(value in request.call_args.args[1] for value in evidence)
        assert len(aggregate.groups) == 1
        assert aggregate.groups[0].summary_data["key_actions"] == (
            evidence if merge_fails else compressed["key_actions"]
        )
        assert aggregate.groups[0].session_uris == tuple(f"codex://s-{index}" for index in range(17))
        assert aggregate.session_count == 17

    @pytest.mark.parametrize("mode", list(CollectMode))
    def test_session_merge_receives_every_chunk_fact(self, mode: CollectMode) -> None:
        field = "scene" if mode is CollectMode.INSIGHT else "key_actions"
        entry = self._entry()
        plan = PlannedCollectEntry(entry, (entry.events, entry.events))
        evidence = [f"evidence-{index:02d}" for index in range(16)]
        compressed = normalize_summary_payload({field: ["all facts compressed"]}, mode=mode)
        with mock.patch(
            "agent_dump.collect_reduction.request_structured_summary_from_llm",
            side_effect=[
                normalize_summary_payload({field: evidence[:8]}, mode=mode),
                normalize_summary_payload({field: evidence[8:]}, mode=mode),
                compressed,
            ],
        ) as request:
            summaries = summarize_collect_entries(
                config=self._config(),
                planned_entries=[plan],
                summary_concurrency=1,
                mode=mode,
                request_structured_summary=request,
            )

        assert request.call_count == 3
        assert request.call_args.kwargs["context"].phase is StructuredSummaryPhase.SESSION_MERGE
        assert all(value in request.call_args.args[1] for value in evidence)
        assert summaries[0].summary_data == compressed

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

    def test_reduce_collect_summaries_reports_tree_progress_across_groups(self) -> None:
        summaries = [
            SessionSummaryEntry(
                collect_entry=replace(
                    self._entry(session_id=f"s-{index}"),
                    project_directory=f"/repo/{index % 2}",
                ),
                summary_data=normalize_summary_payload({"topics": [f"T{index}"], "key_actions": [f"A{index}"]}),
            )
            for index in range(34)
        ]

        progress: list[CollectProgressEvent] = []
        with mock.patch(
            "agent_dump.collect_reduction.request_structured_summary_from_llm",
            return_value=normalize_summary_payload({"topics": ["combined"]}),
        ) as request:
            aggregate = reduce_collect_summaries(
                config=self._config(),
                session_summaries=summaries,
                progress_callback=progress.append,
                request_structured_summary=request,
            )

        assert aggregate.session_count == 34
        assert aggregate.reduction_depth == 2
        assert {group.project_directory for group in aggregate.groups} == {"/repo/0", "/repo/1"}
        assert all(group.date_value == date(2026, 3, 5) for group in aggregate.groups)
        tree_events = [event for event in progress if isinstance(event, TreeReductionProgress)]
        assert [event.level for event in tree_events] == sorted(event.level for event in tree_events)
        for level in range(1, aggregate.reduction_depth + 1):
            level_events = [event for event in tree_events if event.level == level]
            total = level_events[0].total
            assert total > 0
            assert [event.current for event in level_events] == list(range(total + 1))
            assert all(event.total == total for event in level_events)

    def test_reduction_preserves_all_artifacts_by_date_and_project(self) -> None:
        scopes = ((date(2026, 3, 5), "/repo"), (date(2026, 3, 6), "/repo"), (date(2026, 3, 5), "/other"))
        summaries = [
            SessionSummaryEntry(
                replace(
                    self._entry(session_id=f"{scope_index}-{index}"),
                    date_value=day,
                    project_directory=project,
                ),
                normalize_summary_payload({"key_actions": ["shared action"], "artifacts": [f"{scope_index}-{index}"]}),
            )
            for scope_index, (day, project) in enumerate(scopes)
            for index in range(7)
        ]
        request = mock.Mock(side_effect=AssertionError("These summaries do not need compression"))

        aggregate = reduce_collect_summaries(
            config=self._config(), session_summaries=summaries, request_structured_summary=request
        )

        request.assert_not_called()
        assert aggregate.session_count == 21
        assert len(aggregate.groups) == 3
        groups = {(group.date_value, group.project_directory): group for group in aggregate.groups}
        for scope_index, scope in enumerate(scopes):
            assert groups[scope].summary_data["artifacts"] == [f"{scope_index}-{index}" for index in range(7)]
            assert groups[scope].session_uris == tuple(f"codex://{scope_index}-{index}" for index in range(7))

    def test_final_prompt_distinguishes_artifacts_assigned_to_different_projects(self) -> None:
        common_summaries = [
            SessionSummaryEntry(
                replace(self._entry(session_id=f"alpha-{index}"), project_directory="/alpha"),
                normalize_summary_payload({"key_actions": ["shared action"], "artifacts": [artifact]}),
            )
            for index, artifact in enumerate(("component X", "component Y"))
        ]
        beta_entry = replace(self._entry(session_id="beta"), date_value=date(2026, 3, 6), project_directory="/beta")
        request = mock.Mock(side_effect=AssertionError("These summaries do not need compression"))
        prompts: list[str] = []

        for artifact in ("component X", "component Y"):
            aggregate = reduce_collect_summaries(
                config=self._config(),
                session_summaries=[
                    *common_summaries,
                    SessionSummaryEntry(
                        beta_entry,
                        normalize_summary_payload({"key_actions": ["shared action"], "artifacts": [artifact]}),
                    ),
                ],
                request_structured_summary=request,
            )
            prompt = build_collect_final_prompt(
                since_date=date(2026, 3, 5),
                until_date=date(2026, 3, 6),
                aggregate=aggregate,
                has_truncated=False,
            )
            prompts.append(prompt)
            bodies = [
                json.loads(json.loads(line)["content"])
                for line in prompt.splitlines()
                if line.startswith('{"untrusted_data"')
            ]
            groups = {body["project_directory"]: body for body in bodies}
            assert groups["/alpha"]["summary"]["artifacts"] == ["component X", "component Y"]
            assert groups["/beta"]["date"] == "2026-03-06"
            assert groups["/beta"]["session_uris"] == ["codex://beta"]
            assert groups["/beta"]["summary"]["artifacts"] == [artifact]

        request.assert_not_called()
        assert prompts[0] != prompts[1]

    @pytest.mark.parametrize("merge_fails", [False, True])
    def test_compression_and_fallback_keep_date_and_project_groups_separate(self, merge_fails: bool) -> None:
        scopes = ((date(2026, 3, 5), "/repo"), (date(2026, 3, 6), "/repo"), (date(2026, 3, 5), "/other"))
        summaries = [
            SessionSummaryEntry(
                replace(
                    self._entry(session_id=f"{scope_index}-{index}"),
                    date_value=day,
                    project_directory=project,
                ),
                normalize_summary_payload({"artifacts": [f"{scope_index}:artifact-{index}"]}),
            )
            for scope_index, (day, project) in enumerate(scopes)
            for index in range(3)
        ]

        def summarize_group(config: AIConfig, prompt: str, **_kwargs: object) -> dict[str, list[str]]:
            del config
            payloads = [
                json.loads(json.loads(line)["content"])
                for line in prompt.splitlines()
                if line.startswith('{"untrusted_data"')
            ]
            scope_ids = {artifact.split(":")[0] for payload in payloads for artifact in payload["artifacts"]}
            assert len(scope_ids) == 1
            if merge_fails:
                raise RuntimeError("unavailable")
            return normalize_summary_payload({"artifacts": [f"{scope_ids.pop()}:merged"]})

        request = mock.Mock(side_effect=summarize_group)
        with mock.patch("agent_dump.collect_reduction.SESSION_MERGE_LLM_THRESHOLD", 1):
            aggregate = reduce_collect_summaries(
                config=self._config(),
                session_summaries=summaries,
                group_size=2,
                request_structured_summary=request,
            )

        assert request.call_count == 6
        assert aggregate.reduction_depth == 2
        assert len(aggregate.groups) == 3
        groups = {(group.date_value, group.project_directory): group for group in aggregate.groups}
        for scope_index, scope in enumerate(scopes):
            expected = (
                [f"{scope_index}:artifact-{index}" for index in range(3)] if merge_fails else [f"{scope_index}:merged"]
            )
            assert groups[scope].summary_data["artifacts"] == expected
            assert groups[scope].session_uris == tuple(f"codex://{scope_index}-{index}" for index in range(3))

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
        assert len(aggregate.groups) == 1
        assert aggregate.groups[0].summary_data["topics"] == ["T0", "T1"]
        assert aggregate.groups[0].session_uris == ("codex://s-0", "codex://s-1")
        assert records[-1]["event"] == "llm_merge_fallback"
        assert records[-1]["phase"] == "group_merge"
        assert records[-1].get("context") == "collect://group-level-1/group-1", records[-1]
        assert records[-1].get("session_uri") is None

    def test_build_collect_final_prompt_contains_required_sections(self):
        aggregate = CollectAggregate(
            groups=(
                CollectSummaryGroup(
                    date_value=date(2026, 3, 5),
                    project_directory="/repo",
                    session_uris=("codex://s-1",),
                    summary_data=normalize_summary_payload({"topics": ["collect"], "errors": ["timeout"]}),
                ),
            ),
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
        assert len(envelopes) == 1
        assert envelopes[0]["source"] == "collect://final/group/1"
        assert json.loads(envelopes[0]["content"]) == {
            "date": "2026-03-05",
            "project_directory": "/repo",
            "session_uris": ["codex://s-1"],
            "summary": aggregate.groups[0].summary_data,
        }

    @pytest.mark.parametrize(
        ("project_directory", "session_uri", "artifact"),
        [
            ("/repo/" + "x" * 256, "codex://s-1", "artifact"),
            ("/repo", "codex://" + "x" * 256, "artifact"),
            ("/repo", "codex://s-1", 'artifact "quoted"\\path\n' * 16),
        ],
    )
    def test_final_prompt_budget_counts_serialized_metadata_and_summary(
        self, project_directory: str, session_uri: str, artifact: str
    ) -> None:
        aggregate = CollectAggregate(
            groups=(
                CollectSummaryGroup(
                    date_value=date(2026, 3, 5),
                    project_directory=project_directory,
                    session_uris=(session_uri,),
                    summary_data=normalize_summary_payload({"artifacts": [artifact]}),
                ),
            ),
            reduction_depth=0,
        )
        prompt = build_collect_final_prompt(
            since_date=date(2026, 3, 5),
            until_date=date(2026, 3, 5),
            aggregate=aggregate,
            has_truncated=True,
        )

        with mock.patch("agent_dump.collect_prompts.FINAL_PROMPT_CHAR_BUDGET", len(prompt)):
            assert (
                build_collect_final_prompt(
                    since_date=date(2026, 3, 5),
                    until_date=date(2026, 3, 5),
                    aggregate=aggregate,
                    has_truncated=True,
                )
                == prompt
            )
        with (
            mock.patch("agent_dump.collect_prompts.FINAL_PROMPT_CHAR_BUDGET", len(prompt) - 1),
            pytest.raises(ValueError) as error,
        ):
            build_collect_final_prompt(
                since_date=date(2026, 3, 5),
                until_date=date(2026, 3, 5),
                aggregate=aggregate,
                has_truncated=True,
            )

        assert str(error.value) == expect(Keys.COLLECT_FINAL_INPUT_TOO_LARGE, limit=len(prompt) - 1)

    def test_uncompressed_fallback_cannot_bypass_final_prompt_budget(self) -> None:
        artifacts = [f"artifact-{index}:" + "x" * (FINAL_PROMPT_CHAR_BUDGET // 2) for index in range(2)]
        summaries = [
            SessionSummaryEntry(
                self._entry(session_id=f"s-{index}"),
                normalize_summary_payload({"artifacts": [artifact]}),
            )
            for index, artifact in enumerate(artifacts)
        ]
        request = mock.Mock(side_effect=RuntimeError("unavailable"))
        with mock.patch("agent_dump.collect_reduction.SESSION_MERGE_LLM_THRESHOLD", 1):
            aggregate = reduce_collect_summaries(
                config=self._config(), session_summaries=summaries, request_structured_summary=request
            )

        request.assert_called_once()
        assert aggregate.groups[0].summary_data["artifacts"] == artifacts
        with pytest.raises(ValueError) as error:
            build_collect_final_prompt(
                since_date=date(2026, 3, 5),
                until_date=date(2026, 3, 5),
                aggregate=aggregate,
                has_truncated=False,
            )

        assert str(error.value) == expect(Keys.COLLECT_FINAL_INPUT_TOO_LARGE, limit=FINAL_PROMPT_CHAR_BUDGET)
