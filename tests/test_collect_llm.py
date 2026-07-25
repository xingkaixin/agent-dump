from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from typing import Any

import pytest

from agent_dump.collect_llm import LLMRequestError, is_retryable_error, request_summary_from_llm
from agent_dump.config import AIConfig


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
