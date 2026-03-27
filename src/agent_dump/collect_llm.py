"""LLM transport helpers for collect mode."""

import json
from typing import Any, cast
from urllib import error, request

from agent_dump.config import AIConfig
from agent_dump.collect_models import SUMMARY_FIELDS


def request_summary_from_llm(config: AIConfig, prompt: str, *, timeout_seconds: int = 90) -> str:
    """Call provider API and return markdown summary."""
    if config.provider == "openai":
        return _request_openai(config, prompt, timeout_seconds=timeout_seconds)
    if config.provider == "anthropic":
        return _request_anthropic(config, prompt, timeout_seconds=timeout_seconds)
    raise RuntimeError(f"Unsupported provider: {config.provider}")


def request_structured_summary_payload_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int = 90,
) -> str:
    """Call provider API and return one structured summary payload string."""
    if config.provider == "openai":
        return _request_openai_structured_summary(config, prompt, timeout_seconds=timeout_seconds)
    return request_summary_from_llm(config, prompt, timeout_seconds=timeout_seconds)


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _read_openai_response_content(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("OpenAI API response missing content") from exc

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI API returned empty content")
    return content


def _request_openai_json(config: AIConfig, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    url = f"{_normalize_base_url(config.base_url)}/chat/completions"
    req = request.Request(  # noqa: S310
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc}") from exc


def _request_openai(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": "你是一个严谨的工作总结助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "enable_thinking": False,
    }
    return _read_openai_response_content(_request_openai_json(config, payload, timeout_seconds=timeout_seconds))


def _request_openai_structured_summary(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": "你是一个严谨的工作总结助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "enable_thinking": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": build_summary_json_schema(),
        },
    }
    return _read_openai_response_content(_request_openai_json(config, payload, timeout_seconds=timeout_seconds))


def _request_anthropic(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    payload = {
        "model": config.model,
        "max_tokens": 4096,
        "system": "你是一个严谨的工作总结助手。",
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "thinking": {"type": "disabled"},
    }
    body = json.dumps(payload).encode("utf-8")
    url = f"{_normalize_base_url(config.base_url)}/messages"
    req = request.Request(  # noqa: S310
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        raise RuntimeError(f"Anthropic API HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Anthropic API request failed: {exc}") from exc

    try:
        content = data["content"][0]["text"]
    except Exception as exc:
        raise RuntimeError("Anthropic API response missing content") from exc

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Anthropic API returned empty content")
    return content


def build_summary_json_schema() -> dict[str, Any]:
    """Build structured summary JSON schema."""
    return {
        "name": "collect_summary",
        "schema": {
            "type": "object",
            "properties": {field_name: {"type": "array", "items": {"type": "string"}} for field_name in SUMMARY_FIELDS},
            "required": list(SUMMARY_FIELDS),
            "additionalProperties": False,
        },
        "strict": True,
    }
