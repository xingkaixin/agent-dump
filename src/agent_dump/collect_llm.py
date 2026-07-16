"""LLM transport helpers for collect mode."""

import json
import sys
from typing import Any, cast
from urllib import error, request
from urllib.parse import urlsplit

from agent_dump.collect_models import SUMMARY_FIELDS
from agent_dump.config import AIConfig

STRUCTURED_SUMMARY_MAX_TOKENS = 4096
SENSITIVE_REQUEST_HEADERS = frozenset({"authorization", "x-api-key"})


def _warn_if_insecure_base_url(base_url: str) -> None:
    if urlsplit(base_url).scheme.lower() == "https":
        return
    print("警告: AI base_url 未使用 HTTPS，api_key 可能以明文传输。", file=sys.stderr)


def _url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    default_port = {"http": 80, "https": 443}.get(parsed.scheme.lower())
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port or default_port


class _CredentialSafeRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None or _url_origin(req.full_url) == _url_origin(newurl):
            return redirected

        for name, _ in redirected.header_items():
            if name.lower() in SENSITIVE_REQUEST_HEADERS:
                redirected.remove_header(name)
        return redirected


def _open_url(req: request.Request, *, timeout_seconds: int) -> Any:
    opener = request.build_opener(_CredentialSafeRedirectHandler())
    return opener.open(req, timeout=timeout_seconds)  # noqa: S310


def _request_provider_summary(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    if config.provider == "openai":
        return _request_openai(config, prompt, timeout_seconds=timeout_seconds)
    if config.provider == "anthropic":
        return _request_anthropic(config, prompt, timeout_seconds=timeout_seconds)
    raise RuntimeError(f"Unsupported provider: {config.provider}")


def request_summary_from_llm(config: AIConfig, prompt: str, *, timeout_seconds: int = 90) -> str:
    """Call provider API and return markdown summary."""
    _warn_if_insecure_base_url(config.base_url)
    return _request_provider_summary(config, prompt, timeout_seconds=timeout_seconds)


def request_structured_summary_payload_from_llm(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int = 90,
    summary_fields: tuple[str, ...] | None = None,
) -> str:
    """Call provider API and return one structured summary payload string."""
    _warn_if_insecure_base_url(config.base_url)
    if config.provider == "openai":
        return _request_openai_structured_summary(
            config, prompt, timeout_seconds=timeout_seconds, summary_fields=summary_fields
        )
    return _request_provider_summary(config, prompt, timeout_seconds=timeout_seconds)


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
    try:
        return _post_openai_json(config, payload, timeout_seconds=timeout_seconds)
    except RuntimeError as exc:
        # enable_thinking 只有 Qwen 系端点认识；OpenAI 官方 API 会拒绝未知参数，剔除后重试一次
        if "enable_thinking" in payload and "enable_thinking" in str(exc):
            retry_payload = {key: value for key, value in payload.items() if key != "enable_thinking"}
            return _post_openai_json(config, retry_payload, timeout_seconds=timeout_seconds)
        raise


def _post_openai_json(config: AIConfig, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
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
        with _open_url(req, timeout_seconds=timeout_seconds) as resp:
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


def _request_openai_structured_summary(
    config: AIConfig,
    prompt: str,
    *,
    timeout_seconds: int,
    summary_fields: tuple[str, ...] | None = None,
) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": "你是一个严谨的工作总结助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "enable_thinking": False,
        "max_tokens": STRUCTURED_SUMMARY_MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": build_summary_json_schema(summary_fields),
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
        with _open_url(req, timeout_seconds=timeout_seconds) as resp:
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


def build_summary_json_schema(summary_fields: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Build structured summary JSON schema."""
    fields = summary_fields if summary_fields is not None else SUMMARY_FIELDS
    return {
        "name": "collect_summary",
        "schema": {
            "type": "object",
            "properties": {field_name: {"type": "array", "items": {"type": "string"}} for field_name in fields},
            "required": list(fields),
            "additionalProperties": False,
        },
        "strict": True,
    }
