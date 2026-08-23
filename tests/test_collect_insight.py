"""Collect insight-mode tests."""

from datetime import date, datetime, timezone
import io
import json
from unittest import mock

import pytest

from agent_dump.collect_models import (
    INSIGHT_SUMMARY_FIELDS,
    SUMMARY_FIELDS,
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    CollectMode,
    SessionSummaryEntry,
    collect_fields_for,
)
from agent_dump.collect_prompts import (
    build_collect_chunk_prompt,
    build_collect_final_prompt,
    build_collect_merge_prompt,
)
from agent_dump.collect_reduction import _build_summary_bucket_lines
from agent_dump.collect_requests import request_structured_summary_payload_from_llm
from agent_dump.collect_summary import (
    build_summary_json_schema,
    empty_summary_payload,
    merge_summary_payloads,
    normalize_summary_payload,
)
from agent_dump.config import AIConfig


class TestCollectInsightMode:
    def _entry(self, *, text: str = "调试 manage.spec.ts", session_id: str = "s-1") -> CollectEntry:
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

    def test_collect_fields_for_returns_correct_fields(self):
        assert collect_fields_for(CollectMode.PM) == SUMMARY_FIELDS
        assert collect_fields_for(CollectMode.INSIGHT) == INSIGHT_SUMMARY_FIELDS
        assert set(collect_fields_for(CollectMode.INSIGHT)) == {"scene", "stuck", "turning"}

    def test_collect_mode_rejects_unknown_value(self):
        with pytest.raises(ValueError, match="not a valid CollectMode"):
            CollectMode("unknown")

    def test_build_collect_chunk_prompt_insight_mode(self):
        prompt = build_collect_chunk_prompt(
            self._entry(),
            (CollectEvent(kind="user_intent", role="user", text="toBeVisible 断言失败"),),
            chunk_index=0,
            chunk_total=1,
            mode=CollectMode.INSIGHT,
        )

        assert "从用户视角提取给定 chunk" in prompt
        assert "scene" in prompt
        assert "stuck" in prompt
        assert "turning" in prompt
        assert "JSON 必须只包含这些字段: scene, stuck, turning" in prompt
        assert '"source": "codex://s-1#chunk-1/' in prompt
        assert "字符串内部如需引用英文双引号" in prompt

    def test_build_collect_chunk_prompt_pm_mode_unchanged(self):
        prompt = build_collect_chunk_prompt(
            self._entry(),
            (CollectEvent(kind="user_intent", role="user", text="修复"),),
            chunk_index=0,
            chunk_total=1,
            mode=CollectMode.PM,
        )

        assert "工作记录结构化摘要" in prompt
        for field in SUMMARY_FIELDS:
            assert field in prompt

    def test_build_collect_merge_prompt_insight_mode(self):
        entry = self._entry()
        prompt = build_collect_merge_prompt(
            entry=entry,
            payloads=[{"scene": ["S1"], "stuck": [], "turning": ["L1"]}],
            merge_label="session",
            mode=CollectMode.INSIGHT,
        )

        assert "scene, stuck, turning" in prompt
        assert "S1" in prompt

    def test_build_collect_final_prompt_insight_mode(self):
        aggregate = CollectAggregate(
            summary_data=normalize_summary_payload(
                {"scene": ["调试断言"], "stuck": ["断言反复失败"], "turning": ["改用 waitFor"]},
                mode=CollectMode.INSIGHT,
            ),
            date_summaries={"2026-03-05": ["task: 调试断言"]},
            project_summaries={"/repo": ["task: 调试断言"]},
            session_count=1,
            reduction_depth=0,
        )

        prompt = build_collect_final_prompt(
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            aggregate=aggregate,
            has_truncated=False,
            mode=CollectMode.INSIGHT,
        )

        assert "# 作者洞察（2026-03-01 ~ 2026-03-05）" in prompt
        assert "## 洞察" in prompt
        assert "**想做什么**" in prompt
        assert "**卡在哪**" in prompt
        assert "**转折点**" in prompt
        aggregate_envelope = next(
            json.loads(line)
            for line in prompt.splitlines()
            if line.startswith('{"untrusted_data": "untrusted_derived_summary"')
        )
        assert json.loads(aggregate_envelope["content"])["scene"] == ["调试断言"]

    def test_build_summary_json_schema_insight_mode(self):
        schema = build_summary_json_schema(mode=CollectMode.INSIGHT)

        properties = schema["schema"]["properties"]
        assert set(properties) == {"scene", "stuck", "turning"}
        assert schema["schema"]["required"] == ["scene", "stuck", "turning"]
        assert schema["schema"]["additionalProperties"] is False

    def test_normalize_summary_payload_insight_mode(self):
        payload = normalize_summary_payload(
            {"scene": ["调试断言", "调试断言"], "stuck": "断言反复失败", "unknown": ["x"]},
            mode=CollectMode.INSIGHT,
        )

        assert payload["scene"] == ["调试断言"]
        assert payload["stuck"] == ["断言反复失败"]
        assert payload["turning"] == []
        assert set(payload) == {"scene", "stuck", "turning"}

    def test_merge_summary_payloads_insight_mode(self):
        merged = merge_summary_payloads(
            [
                {**empty_summary_payload(CollectMode.INSIGHT), "scene": ["S1"], "turning": ["L1"]},
                {**empty_summary_payload(CollectMode.INSIGHT), "scene": ["S1", "S2"], "stuck": ["C1"]},
            ],
            mode=CollectMode.INSIGHT,
        )

        assert merged["scene"] == ["S1", "S2"]
        assert merged["turning"] == ["L1"]
        assert merged["stuck"] == ["C1"]

    def test_build_summary_bucket_lines_insight_mode(self):
        summaries = [
            SessionSummaryEntry(
                collect_entry=self._entry(),
                summary_data=normalize_summary_payload(
                    {"scene": ["调试断言"], "stuck": ["断言反复失败"], "turning": ["改用 waitFor"]},
                    mode=CollectMode.INSIGHT,
                ),
            ),
        ]

        buckets = _build_summary_bucket_lines(
            summaries,
            key_fn=lambda item: item.collect_entry.date_value.isoformat(),
            mode=CollectMode.INSIGHT,
        )

        assert "2026-03-05" in buckets
        line = buckets["2026-03-05"][0]
        assert "调试断言" in line
        assert "断言反复失败" in line

    def test_empty_summary_payload_insight_mode(self):
        payload = empty_summary_payload(CollectMode.INSIGHT)

        assert set(payload) == {"scene", "stuck", "turning"}
        assert all(v == [] for v in payload.values())

    def test_request_structured_summary_payload_openai_insight_schema(self):
        response = mock.MagicMock()
        response.read.side_effect = io.BytesIO(
            json.dumps({"choices": [{"message": {"content": '{"scene":["S1"],"stuck":[],"turning":["L1"]}'}}]}).encode(
                "utf-8"
            )
        ).read
        response.__enter__.return_value = response
        response.__exit__.return_value = None

        config = AIConfig(
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key="sk-test",
        )
        with mock.patch("agent_dump.collect_llm._open_url", return_value=response) as mock_urlopen:
            result = request_structured_summary_payload_from_llm(
                config,
                "prompt",
                summary_fields=INSIGHT_SUMMARY_FIELDS,
            )

        assert result == '{"scene":["S1"],"stuck":[],"turning":["L1"]}'
        body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        schema = body["response_format"]["json_schema"]
        assert set(schema["schema"]["properties"]) == {"scene", "stuck", "turning"}
        assert body["max_tokens"] == 4096
