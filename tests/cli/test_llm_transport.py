"""Real loopback HTTP boundaries without external models or credentials."""

from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

import pytest
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
    reads = []
    destination = {}

    def respond(handler, _):
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
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(reads) == 2
        header = "authorization" if provider == "openai" else "x-api-key"
        assert all((header in item) == (not cross_origin) for item in reads)


@pytest.mark.parametrize(
    "scenario", ["body-large", "error-large", "invalid-json", "invalid-utf8", "timeout", "redirect-post-307"]
)
def test_response_boundaries(cli, scenario):
    import time

    only_session(cli)

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
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
        assert result.returncode == 1
        assert "private" not in result.stdout + result.stderr
    assert len(calls) == (2 if scenario == "timeout" else 1)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_truncated_report_is_an_error(cli, provider):
    only_session(cli)

    def respond(_, count):
        if count == 1:
            text = json.dumps({"requests": ["fact"]})
            response = (
                {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
                if provider == "openai"
                else {"content": [{"text": text}], "stop_reason": "end_turn"}
            )
        elif provider == "openai":
            response = {"choices": [{"message": {"content": "# Report"}, "finish_reason": "length"}]}
        else:
            response = {"content": [{"text": "# Report"}], "stop_reason": "max_tokens"}
        return 200, {}, json.dumps(response).encode()

    with endpoint(respond) as (url, calls):
        configure(cli, url, provider)
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
        assert result.returncode == 1
        assert "truncated at the output token limit" in result.stdout
        assert not (cli.root / "report.md").exists()
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("scenario", "code", "count"),
    [
        ("429", 0, 3),
        ("503", 0, 3),
        ("401", 1, 1),
        ("thinking", 0, 3),
        ("temperature", 0, 3),
        ("max_tokens", 0, 3),
        ("parse", 0, 3),
        ("invalid", 1, 2),
        ("oversize", 1, 1),
        ("empty", 1, 1),
        ("final-transient", 0, 3),
    ],
)
def test_retry_policy_and_bounded_responses(cli, scenario, code, count):
    only_session(cli)

    def respond(body, number):
        if number == 1:
            if scenario in {"429", "503", "401"}:
                return int(scenario), {"error": {"message": "private remote body"}}
            if scenario in {"thinking", "temperature", "max_tokens"}:
                param = "enable_thinking" if scenario == "thinking" else scenario
                return 400, {"error": {"param": param, "message": "private remote body"}}
            if scenario == "oversize":
                return 200, {"choices": [{"message": {"content": "x" * 262144}}]}
        if scenario == "final-transient" and number == 2:
            return 503, {"error": {"message": "private remote body"}}
        text = json.dumps({"requests": ["fact"]}) if "response_format" in body else "# Final"
        if (scenario == "parse" and number == 1) or scenario == "invalid":
            text = '{"unknown": []}'
        if scenario == "empty":
            text = " "
        return 200, {"choices": [{"message": {"content": text}}]}

    with server(respond) as (url, requests):
        configure(cli, url)
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
    assert result.returncode == code, result.stdout + result.stderr
    assert "private remote body" not in result.stdout + result.stderr
    assert len(requests) == count
    assert (cli.root / "report.md").exists() == (code == 0)
    if scenario == "thinking":
        assert "enable_thinking" not in requests[1][2]
    if scenario == "temperature":
        assert "temperature" not in requests[1][2]
    if scenario == "max_tokens":
        assert "max_tokens" not in requests[1][2]
        assert requests[1][2]["max_completion_tokens"] == 4096
    if scenario in {"parse", "invalid"}:
        assert "untrusted_derived_summary" in requests[1][2]["messages"][-1]["content"]


def set_ai(cli, line):
    path = config_path(cli)
    path.write_text(path.read_text().replace('api_key="fixture-secret"\n', f'api_key="fixture-secret"\n{line}\n'))


def reply(provider):
    def respond(_, number):
        text = json.dumps({"requests": ["fact"]}) if number == 1 else "# Report"
        if provider == "openai":
            return 200, {"choices": [{"message": {"content": text}}]}
        blocks = [{"type": "thinking", "thinking": "plan", "signature": "sig"}, {"type": "text", "text": text}]
        return 200, {"content": blocks}

    return respond


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("reasoning", [None, "default"])
def test_reasoning_controls_thinking_parameters(cli, provider, reasoning):
    only_session(cli)
    with server(reply(provider)) as (url, requests):
        configure(cli, url, provider)
        if reasoning:
            set_ai(cli, f'reasoning="{reasoning}"')
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(requests) == 2
    for _, _, body in requests:
        if reasoning == "default":
            assert "enable_thinking" not in body
            assert "thinking" not in body
        elif provider == "openai":
            assert body["enable_thinking"] is False
        else:
            assert body["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_extra_body_deep_merges_into_requests(cli, provider):
    only_session(cli)
    extra = '[ai.extra_body]\nmax_tokens=8192\n[ai.extra_body.thinking]\ntype="enabled"\nbudget_tokens=1024\n'
    with server(reply(provider)) as (url, requests):
        configure(cli, url, provider, extra)
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
    assert result.returncode == 0, result.stdout + result.stderr
    for _, _, body in requests:
        assert body["max_tokens"] == 8192
        assert body["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_rejected_extra_body_parameter_is_kept(cli):
    only_session(cli)

    def respond(_, number):
        return 400, {"error": {"param": "temperature", "message": "private remote body"}}

    with server(respond) as (url, requests):
        configure(cli, url, extra="[ai.extra_body]\ntemperature=1\n")
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
    assert result.returncode == 1
    assert [body["temperature"] for _, _, body in requests] == [1]


@pytest.mark.parametrize("line", ['reasoning="on"', "reasoning=false", "extra_body=1"])
def test_invalid_reasoning_config_stops_before_requests(cli, line):
    only_session(cli)
    with server(reply("openai")) as (url, requests):
        configure(cli, url)
        set_ai(cli, line)
        result = cli.run(*ARGS, "--save", "report.md", "--lang", "en")
    assert result.returncode == 1
    assert line.split("=")[0] in result.stdout
    assert requests == []


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
