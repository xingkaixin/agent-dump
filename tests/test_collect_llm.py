from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from typing import Any

import pytest

from agent_dump.collect_llm import request_summary_from_llm
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
    warning = capsys.readouterr().err
    assert "base_url 未使用 HTTPS" in warning
    assert "redacted-secret" not in warning


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
