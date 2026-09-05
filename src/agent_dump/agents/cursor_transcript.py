"""Cursor transcript and subagent decoding."""

from collections.abc import Mapping
from datetime import datetime
import json
from typing import Any, Protocol

from agent_dump.agents.base import Session
from agent_dump.agents.cursor_storage import CursorStore, parse_cursor_json
from agent_dump.agents.message_assembly import build_message, build_plan_part, build_text_part, build_tool_part
from agent_dump.agents.message_types import NormalizedMessage, NormalizedPart, NormalizedSessionData
from agent_dump.coercion import safe_epoch_datetime, safe_float, safe_int
from agent_dump.time_utils import normalize_datetime_utc


def parse_cursor_iso_utc(value: str) -> datetime | None:
    """Parse one Cursor ISO timestamp as UTC, or None when it is not ISO.

    Cursor 的 ISO 字段可能不带 offset。naive datetime 交给 astimezone() 或
    timestamp() 会先按主机本地时区解释，同一份数据在 UTC 与 Asia/Shanghai 相差
    8 小时；Session 时间和 bubble 时间必须共用这一个转换事实。
    """
    try:
        return normalize_datetime_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


class CursorSessionBuilder(Protocol):
    def __call__(
        self,
        *,
        composer_id: str,
        request_id: str,
        composer: dict[str, Any],
    ) -> Session: ...


class CursorTranscriptDecoder:
    """Decode Cursor bubbles into normalized transcript data."""

    def __init__(
        self,
        store: CursorStore,
        build_session: CursorSessionBuilder,
    ) -> None:
        self._store = store
        self._build_session = build_session

    def _extract_timestamp(self, bubble: dict[str, Any], fallback_ms: int) -> int:
        created = bubble.get("createdAt")
        if isinstance(created, str):
            parsed = parse_cursor_iso_utc(created)
            if parsed is not None:
                return int(parsed.timestamp() * 1000)
        timing = bubble.get("timingInfo")
        if isinstance(timing, dict):
            for key in ("clientRpcSendTime", "clientSettleTime", "clientEndTime"):
                number = safe_float(timing.get(key), default=float("nan"))
                if safe_epoch_datetime(number, unit="ms") is not None:
                    return safe_int(number, fallback_ms)
        return fallback_ms

    def _extract_text_content(self, bubble: dict[str, Any], role: str) -> str | None:
        if role == "assistant":
            text = bubble.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        code_blocks = bubble.get("codeBlocks")
        if isinstance(code_blocks, list):
            chunks = []
            for block in code_blocks:
                if isinstance(block, dict):
                    content = block.get("content")
                    if isinstance(content, str) and content.strip():
                        chunks.append(content.strip())
            if chunks:
                return "\n\n".join(chunks)
        if role == "assistant":
            thinking = bubble.get("thinking")
            if isinstance(thinking, dict):
                thinking_text = thinking.get("text")
                if isinstance(thinking_text, str) and thinking_text.strip():
                    return thinking_text.strip()
        for key in ("text", "content", "finalText", "message", "markdown", "textDescription"):
            value = bubble.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _normalize_tool_input(self, tool_data: dict[str, Any]) -> Any:
        raw_input = tool_data.get("params")
        if raw_input is None:
            raw_input = tool_data.get("rawArgs")
        if isinstance(raw_input, str):
            try:
                return json.loads(raw_input)
            except json.JSONDecodeError:
                return {"_raw": raw_input}
        return raw_input

    def _extract_tool_status(self, tool_data: dict[str, Any]) -> str | None:
        add = tool_data.get("additionalData")
        status = add.get("status") if isinstance(add, dict) else None
        if status:
            return str(status)
        raw_status = tool_data.get("status")
        return str(raw_status) if raw_status is not None else None

    def _extract_subagent_prompt(self, arguments: Any) -> str:
        if isinstance(arguments, dict):
            prompt = arguments.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
            description = arguments.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
            return json.dumps(arguments, ensure_ascii=False, indent=2)
        if isinstance(arguments, str):
            return arguments
        return json.dumps(arguments, ensure_ascii=False, indent=2)

    def _extract_subagent_type(self, arguments: Any) -> str | None:
        if not isinstance(arguments, dict):
            return None
        subagent_type = arguments.get("subagentType")
        if isinstance(subagent_type, str) and subagent_type.strip():
            return subagent_type.strip()
        return None

    def _build_plan_part(self, tool_data: dict[str, Any], timestamp_ms: int) -> NormalizedPart | None:
        normalized_input = self._normalize_tool_input(tool_data)
        if not isinstance(normalized_input, dict):
            return None
        plan_text = normalized_input.get("plan")
        if not isinstance(plan_text, str) or not plan_text.strip():
            return None

        result = parse_cursor_json(tool_data.get("result"))
        output: str | None = None
        if isinstance(result, dict):
            rejected = result.get("rejected")
            if rejected not in (None, {}, []):
                output = json.dumps(rejected, ensure_ascii=False)

        approval_status = "fail"
        additional_data = tool_data.get("additionalData")
        if isinstance(additional_data, dict):
            review_data = additional_data.get("reviewData")
            if isinstance(review_data, dict):
                selected_option = str(review_data.get("selectedOption") or "").strip().lower()
                if selected_option in {"accept", "accepted", "approve", "approved"}:
                    approval_status = "success"

        return build_plan_part(
            text=plan_text.strip(),
            output=output,
            approval_status=approval_status,
            timestamp_ms=timestamp_ms,
        )

    def _extract_subagent_model(self, composer: dict[str, Any], child_data: Mapping[str, Any]) -> str | None:
        model_config = composer.get("modelConfig")
        if isinstance(model_config, dict):
            model_name = model_config.get("modelName")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()

        for message in child_data.get("messages", []):
            model_name = message.get("model")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()
        return None

    def _build_subagent_completion_message(
        self,
        composer_id: str,
        *,
        expanding: frozenset[str],
        subagent_memo: dict[str, NormalizedMessage | None],
    ) -> NormalizedMessage | None:
        if composer_id in expanding:
            # subagentComposerId 来自 Cursor 的存储，A 引用 B 而 B 又引用 A 会让
            # 展开无限递归；环上的引用退化成普通 tool call
            return None
        if composer_id in subagent_memo:
            return subagent_memo[composer_id]

        completion = self._expand_subagent(composer_id, expanding=expanding, subagent_memo=subagent_memo)
        subagent_memo[composer_id] = completion
        return completion

    def _expand_subagent(
        self,
        composer_id: str,
        *,
        expanding: frozenset[str],
        subagent_memo: dict[str, NormalizedMessage | None],
    ) -> NormalizedMessage | None:
        composer = self._store.composer(composer_id)
        if not composer:
            return None
        child_session = self._build_session(
            composer_id=composer_id,
            request_id=composer_id,
            composer=composer,
        )
        child_data = self._build_session_data(
            child_session,
            expanding=expanding | {composer_id},
            subagent_memo=subagent_memo,
        )
        parts: list[NormalizedPart] = []
        latest_time_created = 0
        for message in child_data.get("messages", []):
            if message.get("role") != "assistant":
                continue
            for part in message.get("parts", []):
                if part.get("type") != "text":
                    continue
                text = part.get("text")
                if not isinstance(text, str):
                    continue
                stripped = text.strip()
                if not stripped or stripped in {"[empty message]", "[corrupted message]"}:
                    continue
                part_time_created = safe_int(part.get("time_created"), safe_int(message.get("time_created")))
                parts.append(
                    {
                        "type": "text",
                        "text": stripped,
                        "time_created": part_time_created,
                    }
                )
                latest_time_created = max(latest_time_created, part_time_created)

        if not parts:
            return None

        message = build_message(
            message_id=f"{composer_id}:subagent-output",
            role="assistant",
            agent="cursor",
            model=self._extract_subagent_model(composer, child_data),
            time_created=latest_time_created,
            tokens={"input": 0, "output": 0},
            parts=parts,
            extra={"subagent_id": composer_id},
        )

        subagent_info = composer.get("subagentInfo")
        if isinstance(subagent_info, dict):
            type_name = subagent_info.get("subagentTypeName")
            if isinstance(type_name, str) and type_name.strip():
                message["subagent_type"] = type_name.strip()
        return message

    def _extract_subagent_id(self, tool_data: dict[str, Any], result: Any) -> str | None:
        parsed_result = parse_cursor_json(result)
        additional_data = tool_data.get("additionalData")
        if isinstance(additional_data, dict):
            candidate_id = additional_data.get("subagentComposerId")
            if isinstance(candidate_id, str) and candidate_id.strip():
                return candidate_id.strip()
        if isinstance(parsed_result, dict):
            candidate_id = parsed_result.get("agentId") or parsed_result.get("agent_id")
            if isinstance(candidate_id, str) and candidate_id.strip():
                return candidate_id.strip()
        return None

    def _extract_tool_part(
        self,
        bubble: dict[str, Any],
        timestamp_ms: int,
        *,
        expanding: frozenset[str] = frozenset(),
        subagent_memo: dict[str, NormalizedMessage | None] | None = None,
    ) -> tuple[NormalizedPart | None, NormalizedMessage | None]:
        tool_data = bubble.get("toolFormerData")
        if not isinstance(tool_data, dict):
            return None, None
        name = tool_data.get("name")
        if not isinstance(name, str) or not name:
            return None, None
        if name == "create_plan":
            return None, None

        normalized_input = self._normalize_tool_input(tool_data)
        status = self._extract_tool_status(tool_data)

        result = tool_data.get("result")
        state: dict[str, Any] = {"status": status, "arguments": normalized_input, "output": None}
        if result is not None:
            state["output"] = result
            if isinstance(result, dict):
                error = result.get("error") or result.get("message") or result.get("stderr")
                if error is not None:
                    state["error"] = error

        normalized_name = "subagent" if "agent" in name.lower() or "task" in name.lower() else name
        subagent_id: str | None = None
        subagent_completion: NormalizedMessage | None = None
        if normalized_name == "subagent":
            state["prompt"] = self._extract_subagent_prompt(normalized_input)
            subagent_type = self._extract_subagent_type(normalized_input)
            if subagent_type:
                state["subagent_type"] = subagent_type
            subagent_id = self._extract_subagent_id(tool_data, result)
            if subagent_id:
                subagent_completion = self._build_subagent_completion_message(
                    subagent_id,
                    expanding=expanding,
                    subagent_memo=subagent_memo if subagent_memo is not None else {},
                )
                if subagent_completion is not None and subagent_completion.get("model"):
                    state["model"] = subagent_completion.get("model")
                if subagent_completion is not None:
                    subagent_type = subagent_completion.get("subagent_type")
                    if isinstance(subagent_type, str) and subagent_type.strip():
                        state["subagent_type"] = subagent_type.strip()
                state["output"] = None

        raw_call_id = tool_data.get("toolCallId") or tool_data.get("callId")
        tool_part = build_tool_part(
            tool_name=normalized_name,
            call_id=raw_call_id if isinstance(raw_call_id, str) else "",
            title=name,
            state=state,
            timestamp_ms=timestamp_ms,
        )
        if normalized_name == "subagent" and subagent_id:
            tool_part["subagent_id"] = subagent_id
            state["subagent_id"] = subagent_id
            subagent_type = state.get("subagent_type")
            if isinstance(subagent_type, str) and subagent_type.strip():
                tool_part["subagent_type"] = subagent_type.strip()
        return tool_part, subagent_completion

    def _extract_tool_parent_message_id(self, bubble: dict[str, Any]) -> str | None:
        """Extract parent message/bubble id for tool attachment when available."""
        candidates: list[Any] = []
        candidates.extend(
            [
                bubble.get("parentMessageId"),
                bubble.get("parentBubbleId"),
            ]
        )
        tool_data = bubble.get("toolFormerData")
        if isinstance(tool_data, dict):
            candidates.extend(
                [
                    tool_data.get("parentMessageId"),
                    tool_data.get("parentBubbleId"),
                    tool_data.get("messageId"),
                ]
            )
            additional_data = tool_data.get("additionalData")
            if isinstance(additional_data, dict):
                candidates.extend(
                    [
                        additional_data.get("parentMessageId"),
                        additional_data.get("parentBubbleId"),
                        additional_data.get("messageId"),
                    ]
                )

        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_tokens(self, bubble: dict[str, Any]) -> tuple[int, int]:
        token_count = bubble.get("tokenCount")
        if isinstance(token_count, dict):
            return safe_int(token_count.get("inputTokens")), safe_int(token_count.get("outputTokens"))
        usage = bubble.get("usage")
        if isinstance(usage, dict):
            return safe_int(usage.get("input_tokens")), safe_int(usage.get("output_tokens"))
        cws = bubble.get("contextWindowStatusAtCreation")
        if isinstance(cws, dict) and cws.get("tokensUsed") is not None:
            return safe_int(cws.get("tokensUsed")), 0
        return 0, 0

    def build_session_data(self, session: Session) -> dict[str, Any]:
        """Build Cursor session data as a unified dictionary."""
        return dict(self._build_session_data(session, expanding=frozenset(), subagent_memo={}))

    def _build_session_data(
        self,
        session: Session,
        *,
        expanding: frozenset[str],
        subagent_memo: dict[str, NormalizedMessage | None],
    ) -> NormalizedSessionData:
        """Build session data, carrying the subagent-expansion context down the recursion.

        `expanding` 是当前正在展开的 composer id 链，用于挡住 subagentComposerId
        形成的引用环；`subagent_memo` 让同一次顶层调用里多个 tool part 指向同一个
        subagent 时只解析一次。两者都随调用链传递而不是挂在实例上，因为
        get_session_data 会被搜索索引的线程池并发调用。
        """
        composer_id = session.metadata.get("composer_id")
        if not isinstance(composer_id, str) or not composer_id:
            composer_id = session.id
        bubble_rows = self._store.transcript_bubbles(composer_id)

        total_input_tokens = 0
        total_output_tokens = 0
        messages: list[NormalizedMessage] = []
        bubble_message_index: dict[str, int] = {}
        fallback_created_ms = int(session.created_at.timestamp() * 1000)
        active_model_name: str | None = None

        for record in bubble_rows:
            bubble_id = record.bubble_id
            bubble = record.data
            if not bubble:
                messages.append(
                    build_message(
                        message_id=bubble_id,
                        role="assistant",
                        agent="cursor",
                        time_created=fallback_created_ms,
                        parts=[build_text_part("[corrupted message]", fallback_created_ms)],
                    )
                )
                continue

            role = "assistant" if bubble.get("type") == 2 else "user"
            timestamp_ms = self._extract_timestamp(bubble, fallback_created_ms)
            model_info = bubble.get("modelInfo")
            model_name = model_info.get("modelName") if isinstance(model_info, dict) else None
            if role == "user" and isinstance(model_name, str) and model_name.strip():
                active_model_name = model_name.strip()
            resolved_model_name = (
                model_name.strip() if isinstance(model_name, str) and model_name.strip() else active_model_name
            )
            in_tokens, out_tokens = self._extract_tokens(bubble)
            total_input_tokens += in_tokens
            total_output_tokens += out_tokens

            text_content = self._extract_text_content(bubble, role)
            tool_data = bubble.get("toolFormerData")
            plan_part = (
                self._build_plan_part(tool_data, timestamp_ms)
                if isinstance(tool_data, dict) and tool_data.get("name") == "create_plan"
                else None
            )
            tool_part, subagent_completion = self._extract_tool_part(
                bubble, timestamp_ms, expanding=expanding, subagent_memo=subagent_memo
            )
            parent_message_id = self._extract_tool_parent_message_id(bubble) if tool_part else None

            if text_content:
                message = build_message(
                    message_id=bubble_id,
                    role=role,
                    agent="cursor",
                    model=resolved_model_name,
                    time_created=timestamp_ms,
                    tokens={"input": in_tokens, "output": out_tokens},
                    parts=[build_text_part(text_content, timestamp_ms)],
                )
                if plan_part:
                    message["parts"].append(plan_part)
                messages.append(message)
                bubble_message_index[bubble_id] = len(messages) - 1

            if tool_part:
                if parent_message_id and parent_message_id in bubble_message_index:
                    parent_idx = bubble_message_index[parent_message_id]
                    messages[parent_idx]["parts"].append(tool_part)
                else:
                    tool_message = build_message(
                        message_id=f"{bubble_id}:tool",
                        role="tool",
                        agent="cursor",
                        mode="tool",
                        model=resolved_model_name,
                        time_created=timestamp_ms,
                        tokens={"input": 0, "output": 0},
                        parts=[tool_part],
                    )
                    messages.append(tool_message)

            if plan_part and not text_content:
                messages.append(
                    build_message(
                        message_id=bubble_id,
                        role="assistant",
                        agent="cursor",
                        model=resolved_model_name,
                        time_created=timestamp_ms,
                        tokens={"input": in_tokens, "output": out_tokens},
                        parts=[plan_part],
                    )
                )
                continue

            if not text_content and not tool_part:
                continue

            if subagent_completion is not None:
                messages.append(subagent_completion)

        messages = sorted(
            messages,
            key=lambda message: safe_int(message.get("time_created"), fallback_created_ms),
        )

        usage_data = session.metadata.get("usage_data")
        usage_context_tokens = None
        usage_context_limit = None
        usage_context_percent = None
        if isinstance(usage_data, dict):
            usage_context_tokens = usage_data.get("contextTokensUsed")
            usage_context_limit = usage_data.get("contextTokenLimit")
            usage_context_percent = usage_data.get("contextUsagePercent")

        return {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": None,
            "version": None,
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": {
                "total_cost": 0,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "message_count": len(messages),
                "context_tokens_used": usage_context_tokens,
                "context_token_limit": usage_context_limit,
                "context_usage_percent": usage_context_percent,
            },
            "metadata": {
                "composer_id": session.metadata.get("composer_id"),
                "request_id": session.metadata.get("request_id"),
                "parent_composer_id": session.metadata.get("parent_composer_id"),
                "subagent_composer_ids": session.metadata.get("subagent_composer_ids"),
            },
            "messages": messages,
        }
