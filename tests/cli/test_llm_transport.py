"""Real loopback HTTP boundaries without external models or credentials."""

from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

from test_collect import ARGS, configure, only_session, server
from test_config_shortcuts import config_path


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
            # ureq pools HTTP/1.0 responses unless told otherwise, racing this handler's close.
            self.send_header("Connection", "close")
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
    # shutdown() 要等一个轮询周期，默认 0.5 秒会加到每个测试上
    worker = threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join()


def test_redirect_does_not_forward_credentials_cross_origin(cli):
    only_session(cli)
    reads = []
    destination = {}

    def respond(handler, _):
        if handler.command == "POST":
            return 302, {"Location": destination["url"] + "/redirected"}, b""
        reads.append({k.lower(): v for k, v in handler.headers.items()})
        text = json.dumps({"requests": ["fact"]}) if len(reads) == 1 else "# Report"
        return 200, {}, json.dumps({"choices": [{"message": {"content": text}}]}).encode()

    with endpoint(respond) as (second, _), endpoint(respond) as (first, _):
        destination["url"] = second
        configure(cli, first)
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(reads) == 2
        assert all("authorization" not in item for item in reads)


def test_truncated_report_is_an_error(cli):
    only_session(cli)

    def respond(_, count):
        if count == 1:
            text = json.dumps({"requests": ["fact"]})
            response = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
        else:
            response = {"choices": [{"message": {"content": "# Report"}, "finish_reason": "length"}]}
        return 200, {}, json.dumps(response).encode()

    with endpoint(respond) as (url, calls):
        configure(cli, url)
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
        assert result.returncode == 1
        assert "truncated at the output token limit" in result.stdout
        assert not (cli.root / "report.md").exists()
    assert len(calls) == 2


def test_collect_log_records_events_without_credentials(cli):
    only_session(cli)

    def respond(body, number):
        text = json.dumps({"requests": ["fact"]}) if "response_format" in body else "# Final"
        return 200, {"choices": [{"message": {"content": '{"unexpected": []}' if number == 1 else text}}]}

    with server(respond) as (url, _):
        configure(cli, url)
        config = config_path(cli)
        config.write_text(config.read_text().replace("enabled=false", 'enabled=true\npath="collect.jsonl"'))
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    log = cli.root / "collect.jsonl"
    events = {json.loads(line)["event"] for line in log.read_text().splitlines()}
    assert {"collect_run_start", "llm_parse_error", "collect_run_finish"} <= events
    assert "fixture-secret" not in log.read_text()
    if os.name != "nt":
        assert log.stat().st_mode & 0o777 == 0o600
