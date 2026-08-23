"""LLM transport helpers for collect mode."""

import json
import sys
from typing import Any, cast
from urllib import error, request
from urllib.parse import urlsplit

from agent_dump.collect_summary import build_summary_json_schema_for_fields
from agent_dump.config import AIConfig, is_loopback_host
from agent_dump.i18n import Keys, i18n
from agent_dump.prompt_safety import summary_system_prompt
from agent_dump.text_safety import safe_display_text

STRUCTURED_SUMMARY_MAX_TOKENS = 4096
# 64 bytes per output token leaves room for JSON and UTF-8 expansion while keeping hostile gateways bounded.
LLM_RESPONSE_MAX_BYTES = 256 * 1024
LLM_ERROR_BODY_MAX_BYTES = 4 * 1024
_RESPONSE_READ_CHUNK_BYTES = 64 * 1024
SENSITIVE_REQUEST_HEADERS = frozenset({"authorization", "x-api-key"})
OPTIONAL_OPENAI_PARAMETERS = frozenset({"enable_thinking"})


class LLMRequestError(RuntimeError):
    """One failed LLM call, carrying enough detail to decide on a retry.

    status 是 HTTP 状态码（无响应的连接/超时故障为 None）。retryable 由此判定：
    对 400/401/403 这类永久失败重发非幂等的 POST，只会让每个 chunk 的延迟和计费翻倍。
    远端错误正文不进入 message；只保留闭集的 rejected_parameters 供请求降级使用。
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        transport: bool = False,
        response_too_large: bool = False,
        rejected_parameters: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.transport = transport
        self.response_too_large = response_too_large
        self.rejected_parameters = frozenset(rejected_parameters)

    @property
    def retryable(self) -> bool:
        if self.response_too_large:
            return False
        if self.transport:
            return True
        if self.status is None:
            return False
        return self.status == 429 or 500 <= self.status < 600


def is_retryable_error(exc: BaseException) -> bool:
    """Whether re-sending the same request could plausibly succeed."""
    if isinstance(exc, LLMRequestError):
        return exc.retryable
    # 未分类的异常（响应解析失败等）保守视为不可重试，避免白付一次调用
    return False


def _warn_if_insecure_base_url(base_url: str) -> None:
    """Warn when a request would carry the key over cleartext to a remote host.

    validate_ai_config 现在会直接拒绝「http + 有 key + 非 loopback」的配置，所以这里
    只剩兜底作用：留给任何绕过校验的调用路径。指向本机的 http 是刻意允许的取舍，
    不再为它每次请求都刷一行告警。
    """
    parsed = urlsplit(base_url)
    if parsed.scheme.lower() == "https" or is_loopback_host(parsed.hostname or ""):
        return
    print(i18n.t(Keys.WARN_INSECURE_BASE_URL), file=sys.stderr)


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


class _ResponseTooLargeError(ValueError):
    def __init__(self, *, limit_bytes: int) -> None:
        super().__init__(f"response exceeded {limit_bytes} bytes")
        self.limit_bytes = limit_bytes


def _declared_content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get("Content-Length")
    if not isinstance(value, (str, bytes)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _read_bounded_body(response: Any, *, limit_bytes: int) -> bytes:
    declared_bytes = _declared_content_length(response)
    if declared_bytes is not None and declared_bytes > limit_bytes:
        raise _ResponseTooLargeError(limit_bytes=limit_bytes)

    body = bytearray()
    while True:
        read_size = min(_RESPONSE_READ_CHUNK_BYTES, limit_bytes - len(body) + 1)
        chunk = response.read(read_size)
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > limit_bytes:
            raise _ResponseTooLargeError(limit_bytes=limit_bytes)


def _read_json_response(response: Any, *, provider_name: str) -> Any:
    try:
        body = _read_bounded_body(response, limit_bytes=LLM_RESPONSE_MAX_BYTES)
    except _ResponseTooLargeError as exc:
        raise LLMRequestError(
            f"{provider_name} API response exceeded {exc.limit_bytes} bytes",
            response_too_large=True,
        ) from exc
    return json.loads(body.decode("utf-8"))


def _find_rejected_parameters(body: bytes, candidates: frozenset[str]) -> frozenset[str]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return frozenset()
    error_payload = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error_payload, dict):
        return frozenset()

    parameter = error_payload.get("param")
    message = error_payload.get("message")
    normalized_message = message.casefold() if isinstance(message, str) else ""
    rejection_markers = (
        "unrecognized request argument",
        "unknown parameter",
        "unsupported parameter",
        "unexpected keyword argument",
        "extra inputs are not permitted",
    )
    return frozenset(
        candidate
        for candidate in candidates
        if parameter == candidate
        or (
            candidate.casefold() in normalized_message
            and any(marker in normalized_message for marker in rejection_markers)
        )
    )


def _normalize_http_error(
    provider_name: str,
    exc: error.HTTPError,
    *,
    optional_parameters: frozenset[str] = frozenset(),
) -> LLMRequestError:
    try:
        body = _read_bounded_body(exc, limit_bytes=LLM_ERROR_BODY_MAX_BYTES) if exc.fp else b""
    except _ResponseTooLargeError as body_error:
        return LLMRequestError(
            f"{provider_name} API HTTP {exc.code}: response body exceeded {body_error.limit_bytes} bytes",
            status=exc.code,
            response_too_large=True,
        )
    except OSError:
        return LLMRequestError(
            f"{provider_name} API HTTP {exc.code}: response body unavailable",
            status=exc.code,
        )

    return LLMRequestError(
        f"{provider_name} API HTTP {exc.code}",
        status=exc.code,
        rejected_parameters=_find_rejected_parameters(body, optional_parameters),
    )


def _normalize_transport_error(provider_name: str, exc: OSError) -> LLMRequestError:
    detail = safe_display_text(str(exc))
    return LLMRequestError(f"{provider_name} API request failed: {detail}", transport=True)


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
    except LLMRequestError as exc:
        # enable_thinking 只有 Qwen 系端点认识；OpenAI 官方 API 会以 4xx 拒绝未知参数，
        # 剔除后重试一次。限定在客户端错误上，避免 5xx/超时也走这条特殊路径。
        is_client_error = exc.status is not None and 400 <= exc.status < 500
        if is_client_error and "enable_thinking" in payload and "enable_thinking" in exc.rejected_parameters:
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
            return cast(dict[str, Any], _read_json_response(resp, provider_name="OpenAI"))
    except error.HTTPError as exc:
        raise _normalize_http_error("OpenAI", exc, optional_parameters=OPTIONAL_OPENAI_PARAMETERS) from exc
    except OSError as exc:
        raise _normalize_transport_error("OpenAI", exc) from exc


def _request_openai(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": summary_system_prompt("你是一个严谨的工作总结助手。")},
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
            {"role": "system", "content": summary_system_prompt("你是一个严谨的工作总结助手。")},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "enable_thinking": False,
        "max_tokens": STRUCTURED_SUMMARY_MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": build_summary_json_schema_for_fields(summary_fields),
        },
    }
    return _read_openai_response_content(_request_openai_json(config, payload, timeout_seconds=timeout_seconds))


def _request_anthropic(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    payload = {
        "model": config.model,
        "max_tokens": 4096,
        "system": summary_system_prompt("你是一个严谨的工作总结助手。"),
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
            data = _read_json_response(resp, provider_name="Anthropic")
    except error.HTTPError as exc:
        raise _normalize_http_error("Anthropic", exc) from exc
    except OSError as exc:
        raise _normalize_transport_error("Anthropic", exc) from exc

    try:
        content = data["content"][0]["text"]
    except Exception as exc:
        raise RuntimeError("Anthropic API response missing content") from exc

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Anthropic API returned empty content")
    return content
