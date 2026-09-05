"""Retry and response handling for collect LLM requests."""

from typing import Protocol
from uuid import uuid4

from agent_dump.collect_llm import (
    is_retryable_error,
    request_structured_summary_payload_from_llm as request_structured_summary_payload_from_llm,
    request_summary_from_llm as _request_summary_from_llm,
)
from agent_dump.collect_logging import CollectLogger
from agent_dump.collect_models import (
    SUMMARY_PARSE_RETRY_COUNT,
    SUMMARY_TRANSPORT_RETRY_COUNT,
    CollectMode,
    StructuredSummaryContext,
    collect_fields_for,
)
from agent_dump.collect_progress import truncate_log_preview, truncate_log_tail
from agent_dump.collect_prompts import build_structured_summary_retry_prompt
from agent_dump.collect_summary import extract_json_object, normalize_summary_payload, validate_summary_payload
from agent_dump.config import AIConfig


class StructuredSummaryRequester(Protocol):
    def __call__(
        self,
        config: AIConfig,
        prompt: str,
        *,
        context: StructuredSummaryContext,
        timeout_seconds: int = 90,
        logger: CollectLogger | None = None,
        mode: CollectMode = CollectMode.PM,
    ) -> dict[str, list[str]]: ...


def request_summary_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int = 90,
    retry_count: int = 1,
) -> str:
    """Call provider API and return markdown summary, retrying transient failures.

    最终 Markdown 渲染是管线末端的单次调用，失败会丢弃整个运行的成果，因此默认重试一次。
    """
    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            return _request_summary_from_llm(config, prompt, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            # 只重试可能因重发而成功的失败。对 400/401/403 这类永久错误重发非幂等的
            # POST，只是把每个 chunk 的延迟与计费翻倍。
            if attempt < retry_count and not is_retryable_error(exc):
                break
    if last_error is None:
        raise RuntimeError("summary request failed without an error")
    raise last_error


def request_structured_summary_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    context: StructuredSummaryContext,
    timeout_seconds: int = 90,
    logger: CollectLogger | None = None,
    mode: CollectMode = CollectMode.PM,
) -> dict[str, list[str]]:
    """Call LLM and parse one structured summary payload."""
    summary_fields = collect_fields_for(mode)
    current_prompt = prompt
    parse_attempt = 0
    transport_attempt = 0
    context_fields = {
        "phase": context.phase.value,
        "context": context.label,
        "session_uri": context.session_uri,
        "chunk_index": context.chunk_index,
        "chunk_total": context.chunk_total,
    }
    while True:
        request_id = str(uuid4())
        attempt_fields = {
            "parse_attempt": parse_attempt + 1,
            "parse_attempt_limit": SUMMARY_PARSE_RETRY_COUNT + 1,
            "transport_attempt": transport_attempt + 1,
            "transport_attempt_limit": SUMMARY_TRANSPORT_RETRY_COUNT + 1,
        }
        if logger is not None:
            logger.log(
                "llm_request",
                request_id=request_id,
                provider=config.provider,
                model=config.model,
                prompt_chars=len(current_prompt),
                **context_fields,
                **attempt_fields,
            )
        try:
            response = request_structured_summary_payload_from_llm(
                config,
                current_prompt,
                timeout_seconds=timeout_seconds,
                summary_fields=summary_fields,
            )
        except Exception as exc:  # noqa: BLE001
            retryable = is_retryable_error(exc)
            will_retry = retryable and transport_attempt < SUMMARY_TRANSPORT_RETRY_COUNT
            if logger is not None:
                logger.log(
                    "llm_request_error",
                    request_id=request_id,
                    provider=config.provider,
                    model=config.model,
                    error=str(exc),
                    retryable=retryable,
                    will_retry=will_retry,
                    retry_kind="transport" if will_retry else None,
                    **context_fields,
                    **attempt_fields,
                )
            if will_retry:
                transport_attempt += 1
                continue
            raise RuntimeError(f"{context.label}: structured summary request failed: {exc}") from exc
        if logger is not None:
            logger.log(
                "llm_response",
                request_id=request_id,
                provider=config.provider,
                model=config.model,
                response_chars=len(response),
                **context_fields,
                **attempt_fields,
            )
        try:
            payload = extract_json_object(response)
            validate_summary_payload(payload, mode=mode)
            return normalize_summary_payload(payload, mode=mode)
        except Exception as exc:  # noqa: BLE001
            will_retry = parse_attempt < SUMMARY_PARSE_RETRY_COUNT
            if logger is not None:
                logger.log(
                    "llm_parse_error",
                    request_id=request_id,
                    provider=config.provider,
                    model=config.model,
                    error=str(exc),
                    response_chars=len(response),
                    response_preview=truncate_log_preview(response),
                    response_tail_preview=truncate_log_tail(response),
                    will_retry=will_retry,
                    retry_kind="parse_correction" if will_retry else None,
                    **context_fields,
                    **attempt_fields,
                )
            if not will_retry:
                raise RuntimeError(f"{context.label}: invalid structured summary response: {exc}") from exc
            parse_attempt += 1
            transport_attempt = 0
            current_prompt = build_structured_summary_retry_prompt(
                original_prompt=prompt,
                invalid_response=response,
                mode=mode,
                request_source=f"{context.phase.value}://request/{request_id}",
            )
