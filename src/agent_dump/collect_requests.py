"""Retry and response handling for collect LLM requests."""

from uuid import uuid4

from agent_dump.collect_llm import (
    is_retryable_error,
    request_structured_summary_payload_from_llm as _request_structured_summary_payload_from_llm,
    request_summary_from_llm as _request_summary_from_llm,
)
from agent_dump.collect_logging import CollectLogger
from agent_dump.collect_models import (
    SUMMARY_PARSE_RETRY_COUNT,
    SUMMARY_TRANSPORT_RETRY_COUNT,
    CollectMode,
    collect_fields_for,
)
from agent_dump.collect_progress import truncate_log_preview, truncate_log_tail
from agent_dump.collect_prompts import _build_structured_summary_retry_prompt
from agent_dump.collect_summary import extract_json_object, normalize_summary_payload
from agent_dump.config import AIConfig


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
    context_label: str,
    timeout_seconds: int = 90,
    parse_retry_count: int = SUMMARY_PARSE_RETRY_COUNT,
    transport_retry_count: int = SUMMARY_TRANSPORT_RETRY_COUNT,
    logger: CollectLogger | None = None,
    phase: str = "structured_summary",
    session_uri: str | None = None,
    chunk_index: int | None = None,
    chunk_total: int | None = None,
    mode: CollectMode = CollectMode.PM,
) -> dict[str, list[str]]:
    """Call LLM and parse one structured summary payload."""
    summary_fields = collect_fields_for(mode)
    current_prompt = prompt
    parse_attempt = 0
    transport_attempt = 0
    while True:
        request_id = str(uuid4())
        attempt_fields = {
            "parse_attempt": parse_attempt + 1,
            "parse_attempt_limit": parse_retry_count + 1,
            "transport_attempt": transport_attempt + 1,
            "transport_attempt_limit": transport_retry_count + 1,
        }
        if logger is not None:
            logger.log(
                "llm_request",
                request_id=request_id,
                phase=phase,
                provider=config.provider,
                model=config.model,
                session_uri=session_uri,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
                prompt_chars=len(current_prompt),
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
            will_retry = retryable and transport_attempt < transport_retry_count
            if logger is not None:
                logger.log(
                    "llm_request_error",
                    request_id=request_id,
                    phase=phase,
                    provider=config.provider,
                    model=config.model,
                    session_uri=session_uri,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    error=str(exc),
                    retryable=retryable,
                    will_retry=will_retry,
                    retry_kind="transport" if will_retry else None,
                    **attempt_fields,
                )
            if will_retry:
                transport_attempt += 1
                continue
            raise RuntimeError(f"{context_label}: structured summary request failed: {exc}") from exc
        if logger is not None:
            logger.log(
                "llm_response",
                request_id=request_id,
                phase=phase,
                provider=config.provider,
                model=config.model,
                session_uri=session_uri,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
                response_chars=len(response),
                **attempt_fields,
            )
        try:
            return normalize_summary_payload(extract_json_object(response), mode=mode)
        except Exception as exc:  # noqa: BLE001
            will_retry = parse_attempt < parse_retry_count
            if logger is not None:
                logger.log(
                    "llm_parse_error",
                    request_id=request_id,
                    phase=phase,
                    provider=config.provider,
                    model=config.model,
                    session_uri=session_uri,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    error=str(exc),
                    response_chars=len(response),
                    response_preview=truncate_log_preview(response),
                    response_tail_preview=truncate_log_tail(response),
                    will_retry=will_retry,
                    retry_kind="parse_correction" if will_retry else None,
                    **attempt_fields,
                )
            if not will_retry:
                raise RuntimeError(f"{context_label}: invalid structured summary response: {exc}") from exc
            parse_attempt += 1
            transport_attempt = 0
            current_prompt = _build_structured_summary_retry_prompt(
                original_prompt=prompt,
                invalid_response=response,
                mode=mode,
                request_source=f"{phase}://request/{request_id}",
            )


def request_structured_summary_payload_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int = 90,
    summary_fields: tuple[str, ...] | None = None,
) -> str:
    """Call provider API and return one structured summary payload string."""
    return _request_structured_summary_payload_from_llm(
        config,
        prompt,
        timeout_seconds=timeout_seconds,
        summary_fields=summary_fields,
    )
