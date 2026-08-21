"""Prompt construction for collect summary stages."""

from datetime import date, tzinfo
import json
from typing import Any

from agent_dump.collect_events import chunk_collect_events, render_collect_event
from agent_dump.collect_llm import build_summary_json_schema as _build_summary_json_schema
from agent_dump.collect_models import (
    CollectAggregate,
    CollectEntry,
    CollectEvent,
    CollectMode,
    collect_fields_for,
)
from agent_dump.collect_progress import truncate_log_preview
from agent_dump.collect_summary import serialize_summary_payload
from agent_dump.prompt_safety import UntrustedData, compose_summary_prompt
from agent_dump.time_utils import get_local_timezone, to_local_datetime


def build_summary_json_schema(mode: CollectMode = CollectMode.PM) -> dict[str, Any]:
    """Build one fixed schema for collect structured summaries."""
    return _build_summary_json_schema(collect_fields_for(mode))


def build_collect_chunk_prompt(
    entry: CollectEntry,
    chunk_events: tuple[CollectEvent, ...],
    *,
    chunk_index: int,
    chunk_total: int,
    local_tz: tzinfo | None = None,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build prompt for a chunk-level structured summary."""
    resolved_local_tz = local_tz or get_local_timezone()
    fields = collect_fields_for(mode)
    if mode is CollectMode.INSIGHT:
        lines = [
            "任务：从用户视角提取给定 chunk 中的关键事实片段。",
            "请只基于给定 chunk 内容输出 JSON 对象，不要输出 Markdown，不要补充解释。",
            f"JSON 必须只包含这些字段: {', '.join(fields)}。",
            "每个字段都必须是字符串数组；没有内容时返回空数组。",
            "字段说明：",
            "- scene: 用户想做什么——目标、意图、正在推进的事。每条一句话。",
            "- stuck: 用户卡在哪——遇到的障碍、反复尝试的地方、报错、犹豫。每条一句话。",
            "- turning: 转折点——思路或行为发生明确变化的时刻（换方案、换工具、换角度）。每条一句话。",
            "要求：",
            "1. 只基于会话中的事实，不要编造。",
            "2. 不要做价值判断或锐评，只描述发生了什么。",
            "3. 同一事实不要换说法重复写。",
            "4. 如果某个字段没有对应内容，返回空数组。",
            "5. 字符串内部如需引用英文双引号，必须按 JSON 规则转义，或改用中文引号。",
        ]
    else:
        lines = [
            "任务：为给定 chunk 生成严谨的工作记录结构化摘要。",
            "请只基于给定 chunk 内容输出 JSON 对象，不要输出 Markdown，不要补充解释。",
            f"JSON 必须只包含这些字段: {', '.join(fields)}。",
            "每个字段都必须是字符串数组；没有内容时返回空数组。",
            "要求：",
            "1. 只保留事实，不要编造。",
            "2. 同一事实不要换说法重复写。",
            "3. errors 只放错误/异常/失败。",
            "4. files 只放文件路径。",
            "5. tools_used 只放工具名。",
            "6. 字符串内部如需引用英文双引号，必须按 JSON 规则转义，或改用中文引号。",
        ]
    metadata_body = "\n".join(
        [
            f"title: {entry.session_title}",
            f"project_directory: {entry.project_directory or '(unknown)'}",
            f"created_at: {to_local_datetime(entry.created_at, resolved_local_tz).isoformat()}",
            f"chunk: {chunk_index + 1}/{chunk_total}",
        ]
    )
    events_body = "\n".join(render_collect_event(event) for event in chunk_events)
    return compose_summary_prompt(
        lines,
        data=(
            UntrustedData(
                kind="session_metadata",
                source=f"{entry.session_uri}#chunk-{chunk_index + 1}/metadata",
                body=metadata_body,
            ),
            UntrustedData(
                kind="session_events",
                source=f"{entry.session_uri}#chunk-{chunk_index + 1}/events",
                body=events_body,
            ),
        ),
    )


def build_collect_merge_prompt(
    *,
    entry: CollectEntry,
    payloads: list[dict[str, list[str]]],
    merge_label: str,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build prompt for session/group structured merge when deterministic merge is too large."""
    fields = collect_fields_for(mode)
    lines = [
        "任务：严谨归并给定的多个结构化摘要。",
        "请把下面多个 JSON 摘要归并成一个 JSON 对象。",
        f"输出 JSON 仍然只能包含这些字段: {', '.join(fields)}。",
        "每个字段必须是字符串数组；没有内容时返回空数组。",
        "要求：去重、保留关键事实、压缩重复表述，不要输出字段之外的内容。",
        "",
        "归并上下文：",
        f"- merge_label: {merge_label}",
    ]
    data = tuple(
        UntrustedData(
            kind="untrusted_derived_summary",
            source=(
                f"{entry.session_uri}#summary-{index}"
                if merge_label == "session"
                else f"collect://{merge_label}/summary/{index}"
            ),
            body=serialize_summary_payload(payload),
        )
        for index, payload in enumerate(payloads, start=1)
    )
    return compose_summary_prompt(lines, data=data)


def _build_structured_summary_retry_prompt(
    *,
    original_prompt: str,
    invalid_response: str,
    mode: CollectMode,
    request_source: str,
) -> str:
    fields = collect_fields_for(mode)
    retry = compose_summary_prompt(
        (
            "上一轮输出不是合法 JSON，不能被解析。",
            "请重新生成完整结果，仍然只输出一个 JSON 对象。",
            f"JSON 只能包含这些字段: {', '.join(fields)}。",
            "每个字段必须是字符串数组；没有内容时返回空数组。",
            "不要输出 Markdown，不要解释，不要保留无效片段。",
            "字符串内部如需引用英文双引号，必须按 JSON 规则转义，或改用中文引号。",
        ),
        data=(
            UntrustedData(
                kind="untrusted_derived_summary",
                source=request_source,
                body=truncate_log_preview(invalid_response, limit=1200),
            ),
        ),
    )
    return "\n\n".join((original_prompt, retry))


def build_collect_session_prompt(
    entry: CollectEntry,
    *,
    source_truncated: bool,
    local_tz: tzinfo | None = None,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build compatibility prompt string for one whole session."""
    chunks = chunk_collect_events(entry.events)
    return build_collect_chunk_prompt(
        entry,
        chunks[0],
        chunk_index=0,
        chunk_total=len(chunks),
        local_tz=local_tz,
        mode=mode,
    ) + ("\n\n注意：原始 session 内容在事件提取阶段已截断。" if source_truncated else "")


def build_collect_final_prompt(
    *,
    since_date: date,
    until_date: date,
    aggregate: CollectAggregate,
    has_truncated: bool,
    mode: CollectMode = CollectMode.PM,
) -> str:
    """Build final collect markdown prompt from the final aggregate."""
    if mode is CollectMode.INSIGHT:
        lines = [
            "任务：从用户视角整理给定聚合数据中的关键事实片段。",
            "请基于给定的结构化聚合数据输出 Markdown，只摆事实，不做评价。",
            "必须严格使用以下结构：",
            f"# 作者洞察（{since_date.isoformat()} ~ {until_date.isoformat()}）",
            "",
            "## 洞察",
            "",
            "每条洞察用以下格式（scene/stuck/turning 三个维度交叉组合，不要求每条都齐备）：",
            "### [简短标题]",
            "- **想做什么**: [用户的目标或意图]",
            "- **卡在哪**: [遇到的障碍或反复尝试的地方]",
            "- **转折点**: [思路或行为发生明确变化的时刻]",
            "",
            "要求：",
            "1. 从聚合数据中提炼，同一 session 的相关事实合并。",
            "2. 只描述事实，不做价值判断。",
            "3. 如果某个维度没有内容，省略该行。",
        ]
    else:
        lines = [
            "任务：分析给定的结构化聚合数据并生成工作记录。",
            "请基于给定的结构化聚合数据输出 Markdown，总结重点工作。",
            "必须严格使用以下结构：",
            f"# 时段工作总结（{since_date.isoformat()} ~ {until_date.isoformat()}）",
            "## 按日期",
            "## 按项目/目录",
            "## 重点事项（决策/风险/阻塞）",
            "## 产出清单",
            "## 下一步建议",
            "要求：避免空话，按事实归纳；同一事项合并去重；可按优先级标注。",
        ]

    lines.extend(
        [
            "",
            f"- session_count: {aggregate.session_count}",
            f"- reduction_depth: {aggregate.reduction_depth}",
        ]
    )
    if has_truncated:
        lines.append("注意：部分 session 在事件提取阶段达到预算上限，最终结论可能遗漏低优先级细节。")

    data = [
        UntrustedData(
            kind="untrusted_derived_summary",
            source="collect://final/aggregate",
            body=serialize_summary_payload(aggregate.summary_data),
        )
    ]
    data.extend(
        UntrustedData(
            kind="date_summary_bucket",
            source=f"collect://final/date/{index}",
            body=json.dumps({"bucket": bucket, "values": values}, ensure_ascii=False),
        )
        for index, (bucket, values) in enumerate(aggregate.date_summaries.items(), start=1)
    )
    data.extend(
        UntrustedData(
            kind="project_summary_bucket",
            source=f"collect://final/project/{index}",
            body=json.dumps({"bucket": bucket, "values": values}, ensure_ascii=False),
        )
        for index, (bucket, values) in enumerate(aggregate.project_summaries.items(), start=1)
    )
    return compose_summary_prompt(lines, data=tuple(data))
