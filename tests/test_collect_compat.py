"""Collect compatibility import tests."""

from types import ModuleType

import pytest

from agent_dump import (
    collect,
    collect_dates,
    collect_events,
    collect_logging,
    collect_models,
    collect_output,
    collect_prompts,
    collect_reduction,
    collect_requests,
    collect_sessions,
    collect_summary,
)


@pytest.mark.parametrize(
    ("name", "owner"),
    (
        ("parse_user_date", collect_dates),
        ("resolve_collect_date_range", collect_dates),
        ("chunk_collect_events", collect_events),
        ("extract_collect_events", collect_events),
        ("CollectLogger", collect_logging),
        ("CollectAggregate", collect_models),
        ("CollectEntry", collect_models),
        ("CollectEvent", collect_models),
        ("CollectProgressEvent", collect_models),
        ("MergeSessionsProgress", collect_models),
        ("PlanChunksProgress", collect_models),
        ("PlannedCollectEntry", collect_models),
        ("ScanSessionsProgress", collect_models),
        ("SessionSummaryEntry", collect_models),
        ("StructuredSummaryContext", collect_models),
        ("StructuredSummaryPhase", collect_models),
        ("SummarizeChunksProgress", collect_models),
        ("TreeReductionProgress", collect_models),
        ("write_collect_markdown", collect_output),
        ("build_collect_chunk_prompt", collect_prompts),
        ("build_collect_final_prompt", collect_prompts),
        ("build_collect_merge_prompt", collect_prompts),
        ("build_collect_session_prompt", collect_prompts),
        ("reduce_collect_summaries", collect_reduction),
        ("summarize_collect_entries", collect_reduction),
        ("request_structured_summary_from_llm", collect_requests),
        ("request_structured_summary_payload_from_llm", collect_requests),
        ("request_summary_from_llm", collect_requests),
        ("collect_entries", collect_sessions),
        ("plan_collect_entries", collect_sessions),
        ("build_summary_json_schema", collect_summary),
    ),
)
def test_compatibility_name_references_owning_module(name: str, owner: ModuleType) -> None:
    assert getattr(collect, name) is getattr(owner, name)
