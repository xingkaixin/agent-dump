"""Real loopback HTTP boundaries without external models or credentials."""

from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
from test_collect import ARGS, configure, only_session


@contextmanager
def endpoint(callback):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.handle_request()

        def do_GET(self):
            self.handle_request()

        def handle_request(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw) if raw else None
            calls.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            status, headers, data = callback(self, len(calls))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            if "Content-Length" not in headers:
                self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join()


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("cross_origin", [False, True])
def test_redirect_credentials(cli, provider, cross_origin):
    only_session(cli)
    results = []
    for candidate in ["python", "rust"]:
        reads = []
        destination = {}

        def respond(handler, _, reads=reads, destination=destination):
            if handler.command == "POST":
                return 302, {"Location": destination["url"] + "/redirected"}, b""
            reads.append({k.lower(): v for k, v in handler.headers.items()})
            text = json.dumps({"requests": ["fact"]}) if len(reads) == 1 else "# Report"
            response = (
                {"choices": [{"message": {"content": text}}]} if provider == "openai" else {"content": [{"text": text}]}
            )
            return 200, {}, json.dumps(response).encode()

        with endpoint(respond) as (second, _), endpoint(respond) as (first, _):
            destination["url"] = second if cross_origin else first
            configure(cli, first, provider)
            result = cli.run(candidate, *ARGS, "--save", "report.md", "--lang", "en")
            results.append((result.returncode, result.stdout, result.stderr))
            assert result.returncode == 0, result.stdout + result.stderr
            assert len(reads) == 2
            header = "authorization" if provider == "openai" else "x-api-key"
            assert all((header in item) == (not cross_origin) for item in reads)
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "scenario", ["body-large", "error-large", "invalid-json", "invalid-utf8", "timeout", "redirect-post-307"]
)
def test_response_boundaries(cli, scenario):
    import time

    only_session(cli)
    results = []
    counts = []
    for candidate in ["python", "rust"]:

        def respond(_, count):
            if scenario == "body-large":
                return 200, {}, b" " * (256 * 1024 + 1)
            if scenario == "error-large":
                return 503, {}, b"private" * 1000
            if scenario == "invalid-json":
                return 200, {}, b"{broken"
            if scenario == "invalid-utf8":
                return 200, {}, b"\xff"
            if scenario == "timeout":
                time.sleep(2.2)
                return 200, {}, b"{}"
            return 307, {"Location": "/elsewhere"}, b""

        with endpoint(respond) as (url, calls):
            configure(cli, url)
            result = cli.run(candidate, *ARGS, "--save", "report.md", "--lang", "en")
            results.append((result.returncode, result.stdout, result.stderr))
            counts.append(len(calls))
            assert result.returncode == 1
            assert "private" not in result.stdout + result.stderr
    assert counts == ([2, 2] if scenario == "timeout" else [1, 1])
    assert results[0] == results[1]
