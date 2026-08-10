from collections.abc import Iterator
from contextlib import contextmanager
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from threading import Thread
from typing import Any
from unittest import mock
from urllib import error as urllib_error

import pytest

from agent_dump import collect_llm
from agent_dump.collect_llm import LLMRequestError, is_retryable_error, request_summary_from_llm
from agent_dump.config import AIConfig
from agent_dump.prompt_safety import UNTRUSTED_DATA_RULES, summary_system_prompt
from agent_dump.text_safety import has_unsafe_line_characters


class _StreamingResponse(io.BytesIO):
    def __init__(self, body: bytes, *, content_length: int | str | None = None) -> None:
        super().__init__(body)
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}
        self.read_sizes: list[int] = []
        self.bytes_read = 0

    def read(self, size: int | None = -1, /) -> bytes:
        self.read_sizes.append(-1 if size is None else size)
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


@contextmanager
def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _redirect_handler(target_url: str, received_headers: dict[str, str]) -> type[BaseHTTPRequestHandler]:
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received_headers.update({name.lower(): value for name, value in self.headers.items()})
            self.send_response(302)
            self.send_header("Location", target_url)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            del format, args

    return RedirectHandler


def _response_handler(
    response_payload: dict[str, Any], received_headers: dict[str, str]
) -> type[BaseHTTPRequestHandler]:
    class ResponseHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            received_headers.update({name.lower(): value for name, value in self.headers.items()})
            body = json.dumps(response_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            del format, args

    return ResponseHandler


@pytest.mark.parametrize(
    ("provider", "credential_header", "response_payload"),
    [
        ("openai", "authorization", {"choices": [{"message": {"content": "ok"}}]}),
        ("anthropic", "x-api-key", {"content": [{"text": "ok"}]}),
    ],
)
def test_cross_origin_redirect_does_not_forward_credentials(
    provider: str,
    credential_header: str,
    response_payload: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    initial_headers: dict[str, str] = {}
    redirected_headers: dict[str, str] = {}
    with _serve(_response_handler(response_payload, redirected_headers)) as target_server:
        target_url = f"http://localhost:{target_server.server_port}/redirected"
        with _serve(_redirect_handler(target_url, initial_headers)) as redirect_server:
            result = request_summary_from_llm(
                AIConfig(
                    provider=provider,
                    base_url=f"http://127.0.0.1:{redirect_server.server_port}/v1",
                    model="test-model",
                    api_key="redacted-secret",
                ),
                "prompt",
                timeout_seconds=5,
            )

    assert result == "ok"
    assert credential_header in initial_headers
    assert credential_header not in redirected_headers
    # 本测试只关心重定向不带走凭证；明文告警的边界由 TestInsecureBaseUrlWarning 覆盖
    assert "redacted-secret" not in capsys.readouterr().err


def test_same_origin_redirect_preserves_credentials(capsys: pytest.CaptureFixture[str]) -> None:
    redirected_headers: dict[str, str] = {}

    class SameOriginHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(302)
            self.send_header("Location", "/redirected")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            redirected_headers.update({name.lower(): value for name, value in self.headers.items()})
            body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            del format, args

    with _serve(SameOriginHandler) as server:
        result = request_summary_from_llm(
            AIConfig(
                provider="openai",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model="test-model",
                api_key="redacted-secret",
            ),
            "prompt",
            timeout_seconds=5,
        )

    assert result == "ok"
    assert "authorization" in redirected_headers
    assert "redacted-secret" not in capsys.readouterr().err


class TestRetryClassification:
    """AD-130：只重试可能因重发而成功的失败。"""

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 599])
    def test_retryable_statuses(self, status):
        assert is_retryable_error(LLMRequestError("x", status=status))

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 499])
    def test_permanent_statuses(self, status):
        assert not is_retryable_error(LLMRequestError("x", status=status))

    def test_transport_failures_are_retryable(self):
        assert is_retryable_error(LLMRequestError("connection reset", transport=True))

    def test_error_without_status_or_transport_is_not_retryable(self):
        assert not is_retryable_error(LLMRequestError("weird"))

    def test_unrelated_exceptions_are_not_retryable(self):
        assert not is_retryable_error(RuntimeError("missing content"))
        assert not is_retryable_error(ValueError("bad"))

    def test_status_is_preserved_for_reporting(self):
        exc = LLMRequestError("OpenAI API HTTP 503: busy", status=503)

        assert exc.status == 503
        assert "503" in str(exc)


class TestBoundedResponses:
    @staticmethod
    def _config(provider: str = "openai") -> AIConfig:
        return AIConfig(
            provider=provider,
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key="redacted-secret",
        )

    def test_reader_accepts_a_body_exactly_at_the_limit(self) -> None:
        response = _StreamingResponse(b"x" * 64, content_length=64)

        assert collect_llm._read_bounded_body(response, limit_bytes=64) == b"x" * 64
        assert response.read_sizes
        assert all(size > 0 for size in response.read_sizes)

    def test_response_limit_accommodates_a_large_valid_structured_payload(self) -> None:
        content = json.dumps({"topics": ["总结" * 8192]}, ensure_ascii=False)
        body = json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode("utf-8")
        response = _StreamingResponse(body, content_length=len(body))

        with mock.patch("agent_dump.collect_llm._open_url", return_value=response):
            result = request_summary_from_llm(self._config(), "prompt")

        assert result == content
        assert len(body) < collect_llm.LLM_RESPONSE_MAX_BYTES
        assert all(size > 0 for size in response.read_sizes)

    def test_declared_oversized_success_body_is_rejected_without_reading(self) -> None:
        response = _StreamingResponse(b"unused", content_length=collect_llm.LLM_RESPONSE_MAX_BYTES + 1)

        with (
            mock.patch("agent_dump.collect_llm._open_url", return_value=response),
            pytest.raises(LLMRequestError, match="response exceeded") as raised,
        ):
            request_summary_from_llm(self._config(), "prompt")

        assert not is_retryable_error(raised.value)
        assert response.read_sizes == []

    def test_streamed_oversized_success_body_stops_at_limit_plus_one(self) -> None:
        limit = collect_llm.LLM_RESPONSE_MAX_BYTES
        response = _StreamingResponse(b"x" * (limit + 4096))

        with (
            mock.patch("agent_dump.collect_llm._open_url", return_value=response),
            pytest.raises(LLMRequestError, match="response exceeded") as raised,
        ):
            request_summary_from_llm(self._config(), "prompt")

        assert not is_retryable_error(raised.value)
        assert response.bytes_read == limit + 1
        assert max(response.read_sizes) <= collect_llm._RESPONSE_READ_CHUNK_BYTES

    def test_malformed_content_length_falls_back_to_bounded_streaming(self) -> None:
        response = _StreamingResponse(b"payload", content_length="not-a-number")

        assert collect_llm._read_bounded_body(response, limit_bytes=64) == b"payload"
        assert response.read_sizes

    def test_oversized_http_error_has_a_sanitized_bounded_preview(self) -> None:
        body = b"bad\x1b[31m\n" + b"x" * collect_llm.LLM_ERROR_BODY_MAX_BYTES + b"remote-tail"
        response = _StreamingResponse(body)
        http_error = urllib_error.HTTPError(
            "https://api.example.com/v1/chat/completions",
            503,
            "Service Unavailable",
            Message(),
            response,
        )

        with (
            mock.patch("agent_dump.collect_llm._open_url", side_effect=http_error),
            pytest.raises(LLMRequestError) as raised,
        ):
            request_summary_from_llm(self._config(), "prompt")

        error_text = str(raised.value)
        assert raised.value.status == 503
        assert raised.value.response_too_large is True
        assert not is_retryable_error(raised.value)
        assert len(error_text) < 700
        assert not has_unsafe_line_characters(error_text)
        assert "remote-tail" not in error_text
        assert "redacted-secret" not in error_text
        assert response.bytes_read == collect_llm.LLM_ERROR_BODY_MAX_BYTES + 1

    @pytest.mark.parametrize("transport_error", [TimeoutError("timed out"), ConnectionResetError("reset")])
    def test_low_level_transport_errors_are_classified_for_retry(self, transport_error: OSError) -> None:
        with (
            mock.patch("agent_dump.collect_llm._open_url", side_effect=transport_error),
            pytest.raises(LLMRequestError) as raised,
        ):
            request_summary_from_llm(self._config(), "prompt")

        assert is_retryable_error(raised.value)
        assert "redacted-secret" not in str(raised.value)


class TestInsecureBaseUrlWarning:
    """AD-130：明文告警只对远端 http 有意义；本机 http 是刻意允许的用例。"""

    def test_remote_http_warns(self, capsys):
        from agent_dump.collect_llm import _warn_if_insecure_base_url

        _warn_if_insecure_base_url("http://api.example.com/v1")

        assert "base_url 未使用 HTTPS" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "base_url",
        ["http://localhost:11434/v1", "http://127.0.0.1:8000/v1", "http://[::1]:8000/v1"],
    )
    def test_loopback_http_does_not_warn(self, base_url, capsys):
        """否则本机 gateway 用户每个请求都会看到一行无从处理的告警。"""
        from agent_dump.collect_llm import _warn_if_insecure_base_url

        _warn_if_insecure_base_url(base_url)

        assert capsys.readouterr().err == ""

    def test_https_does_not_warn(self, capsys):
        from agent_dump.collect_llm import _warn_if_insecure_base_url

        _warn_if_insecure_base_url("https://api.example.com/v1")

        assert capsys.readouterr().err == ""


class TestSystemMessageDeclaresUntrustedData:
    """AD-167：固定规则必须在 system message，与 user message 里的数据分处不同 role。"""

    @staticmethod
    def _captured_payload(monkeypatch, request_fn, *args, **kwargs) -> dict:
        captured: dict = {}

        def fake_request(config, payload, *, timeout_seconds):
            captured.update(payload)
            return {"choices": [{"message": {"content": '{"done": []}'}}]}

        monkeypatch.setattr(collect_llm, "_request_openai_json", fake_request)
        request_fn(*args, **kwargs)
        return captured

    @pytest.mark.parametrize(
        "request_fn_name",
        ["_request_openai", "_request_openai_structured_summary"],
    )
    def test_rules_live_in_the_system_message(self, monkeypatch, request_fn_name):
        config = AIConfig(provider="openai", base_url="https://x", model="m", api_key="k")
        request_fn = getattr(collect_llm, request_fn_name)

        payload = self._captured_payload(monkeypatch, request_fn, config, "user prompt", timeout_seconds=1)

        roles = {message["role"]: message["content"] for message in payload["messages"]}
        assert set(roles) == {"system", "user"}
        for rule in UNTRUSTED_DATA_RULES:
            assert rule in roles["system"], "规则必须在 system，不能混进用户数据那一侧"
            assert rule not in roles["user"]
        assert roles["system"] == summary_system_prompt("你是一个严谨的工作总结助手。")
        assert roles["user"] == "user prompt", "user message 只承载数据，不被改写"

    def test_anthropic_uses_the_same_system_safety_rules(self, monkeypatch):
        response = mock.MagicMock()
        response.read.side_effect = io.BytesIO(b'{"content":[{"text":"ok"}]}').read
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        captured: dict = {}

        def fake_open(req, *, timeout_seconds):
            del timeout_seconds
            captured.update(json.loads(req.data.decode("utf-8")))
            return response

        monkeypatch.setattr(collect_llm, "_open_url", fake_open)
        collect_llm._request_anthropic(
            AIConfig(provider="anthropic", base_url="https://x", model="m", api_key="k"),
            "user prompt",
            timeout_seconds=1,
        )

        for rule in UNTRUSTED_DATA_RULES:
            assert rule in captured["system"]
            assert rule not in captured["messages"][0]["content"]
        assert captured["system"] == summary_system_prompt("你是一个严谨的工作总结助手。")
        assert captured["messages"] == [{"role": "user", "content": "user prompt"}]
