"""Collect contracts exercised through both CLIs and a local HTTP endpoint."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from cli_fixture import header, message
import pytest
from test_config_shortcuts import config_path

ARGS = ["--collect", "--since", "2026-01-15", "--until", "2026-01-15", "-q", "provider:codex"]


@contextmanager
def server(responder):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, dict(self.headers), body))
            status, response = responder(body, len(requests))
            data = json.dumps(response, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/v1", requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def configure(cli, url, provider="openai", extra=""):
    config_path(cli).write_text(
        f'[ai]\nprovider="{provider}"\nbase_url="{url}"\nmodel="fixture-model"\napi_key="fixture-secret"\n'
        "[collect]\nsummary_concurrency=1\nsummary_timeout_seconds=2\n"
        "[logging]\nenabled=false\n" + extra
    )


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("extra", [[], ["--save", "reports"], ["--save", "report.MD"], ["--collect-mode", "insight"]])
def test_dry_run(cli, lang, extra):
    cli.parity(*ARGS, "--dry-run", "--lang", lang, *extra)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "dates",
    [
        [],
        ["--since", "2026-01-15"],
        ["--until", "2026-01-15"],
        ["--since", "bad"],
        ["--since", "20260115", "--until", "2026-1-15"],
        ["--since", "2026-02-01", "--until", "2026-01-01"],
    ],
)
def test_date_ranges(cli, lang, dates):
    args = ["--collect", "--dry-run", "-q", "provider:codex", "--lang", lang, *dates]
    result = cli.run("python", *args)
    cli.parity(*args, exit_code=result.returncode)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("mode", ["pm", "insight"])
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_collect_requests_and_output(cli, provider, mode, lang):
    for source in cli.source.parent.rglob("*.jsonl"):
        if source != cli.source:
            source.unlink()
    cli.write(
        [
            header(cwd="  /project/./nested//  "),
            message("user", "请检查认证问题"),
            message("assistant", "认证缺陷已修复 😺"),
        ]
    )
    fields = ["requests", "decisions", "outcomes"] if mode == "pm" else ["scene", "stuck", "turning"]
    summary = json.dumps({field: [f"{field} fact"] for field in fields}, ensure_ascii=False)
    calls = []
    results = []
    files = []
    for candidate in ["python", "rust"]:

        def respond(body, count):
            text = summary if count == 1 else "# 报告\n\n已修复认证缺陷。"
            return 200, (
                {"choices": [{"message": {"content": text}}]}
                if provider == "openai"
                else {"content": [{"type": "text", "text": text}]}
            )

        with server(respond) as (url, requests):
            configure(cli, url, provider)
            result = cli.run(candidate, *ARGS, "--collect-mode", mode, "--save", "report.md", "--lang", lang)
            assert result.returncode == 0, result.stdout + result.stderr
            results.append((result.stdout, result.stderr))
            files.append((cli.root / "report.md").read_bytes())
            calls.append([(path, body) for path, _, body in requests])
            assert all("fixture-secret" in str(headers) for _, headers, _ in requests)
    assert calls[0] == calls[1]
    assert files[0] == files[1]
    assert results[0] == results[1]


def only_session(cli):
    for path in (cli.root / "sources" / "codex" / "sessions").rglob("*.jsonl"):
        if path != cli.source:
            path.unlink()


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "config",
    [
        None,
        'bad = "unterminated',
        "[agent.codex]\ndeny=42\n",
        '[agent.codex]\ndeny=["/project"]\n',
        "[agent]\ncodex=42\n",
        "[agent.codex]\ndeny=[0]\n",
        '[agent.codex]\ndeny=[""]\n',
    ],
)
def test_collect_config_validation(cli, lang, config):
    if config is not None:
        config_path(cli).write_text(config)
    args = [*ARGS, "--dry-run", "--lang", lang]
    expected = cli.run("python", *args).returncode
    cli.parity(*args, exit_code=expected)


@pytest.mark.parametrize("mode", ["pm", "insight"])
def test_handoff_manifest(cli, mode):
    results = []
    source_before = cli.fixtures.source_manifest(cli.root)
    for candidate in ["python", "rust"]:
        result = cli.run(candidate, *ARGS, "--emit-prompt", "--collect-mode", mode)
        assert result.returncode == 0, result.stdout + result.stderr
        normalized = []
        for line in result.stdout.splitlines():
            if not line.startswith('{"untrusted_data"'):
                normalized.append(line)
                continue
            envelope = json.loads(line)
            content = json.loads(envelope["content"])
            content.pop("generated_at", None)
            if "read_argv" in content:
                assert content["read_argv"][-3:] == [content["uri"], "--format", "print"]
                content.pop("read_argv")
                content.pop("read_command")
            envelope.pop("length")
            envelope["content"] = content
            normalized.append(envelope)
        results.append((normalized, result.stderr))
        assert source_before == cli.fixtures.source_manifest(cli.root)
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "scenario", ["429", "503", "401", "thinking", "parse", "invalid", "oversize", "empty", "final-transient"]
)
def test_retry_policy_and_bounded_responses(cli, scenario):
    only_session(cli)
    requests_by_candidate = []
    results = []
    for candidate in ["python", "rust"]:

        def respond(body, count):
            structured = "response_format" in body
            if count == 1:
                if scenario in {"429", "503", "401"}:
                    return int(scenario), {"error": {"message": "private remote body"}}
                if scenario == "thinking":
                    return 400, {"error": {"param": "enable_thinking", "message": "private remote body"}}
                if scenario == "oversize":
                    return 200, {"choices": [{"message": {"content": "x" * 262144}}]}
            if scenario == "final-transient" and count == 2:
                return 503, {"error": {"message": "private remote body"}}
            text = json.dumps({"requests": ["Straße", "STRASSE", " one\n fact "]}) if structured else "# Final"
            if (scenario == "parse" and count == 1) or scenario == "invalid":
                text = '{"unknown": []}'
            if scenario == "malformed":
                text = "not JSON"
            if scenario == "empty":
                text = " "
            return 200, {"choices": [{"message": {"content": text}}]}

        with server(respond) as (url, requests):
            configure(cli, url)
            result = cli.run(candidate, *ARGS, "--save", "report.md", "--lang", "en")
            assert "private remote body" not in result.stdout + result.stderr
            results.append((result.returncode, result.stdout, result.stderr))
            requests_by_candidate.append(len(requests))
            if scenario == "thinking":
                assert "enable_thinking" not in requests[1][2]
            if scenario in {"parse", "invalid"}:
                assert "untrusted_derived_summary" in requests[1][2]["messages"][-1]["content"]
    assert requests_by_candidate[0] == requests_by_candidate[1]
    assert results[0] == results[1]


@pytest.mark.parametrize("formats", ["json", "json,md,raw,print", "md,print"])
@pytest.mark.parametrize("scenario", ["success", "missing-config", "incomplete-config", "401"])
def test_uri_summary(cli, formats, scenario):
    import shutil

    from cli_fixture import IDENTITY

    results = []
    files = []
    calls = []
    for candidate in ["python", "rust"]:

        def respond(body, count):
            return (401, {}) if scenario == "401" else (200, {"choices": [{"message": {"content": "# Summary"}}]})

        with server(respond) as (url, requests):
            configure(cli, url)
            if scenario == "missing-config":
                config_path(cli).unlink()
            if scenario == "incomplete-config":
                config_path(cli).write_text('[ai]\nprovider="openai"\n')
            shutil.rmtree(cli.root / "exports", ignore_errors=True)
            result = cli.run(
                candidate,
                f"codex://{IDENTITY}",
                "--summary",
                "--format",
                formats,
                "--output",
                "exports",
                "--lang",
                "en",
            )
            results.append((result.returncode, result.stdout, result.stderr))
            calls.append([body for _, _, body in requests])
            files.append(
                {
                    str(p.relative_to(cli.root)): json.loads(p.read_text()) if p.suffix == ".json" else p.read_bytes()
                    for p in (cli.root / "exports").rglob("*")
                    if p.is_file()
                }
            )
    assert calls[0] == calls[1]
    assert files[0] == files[1]
    assert results[0] == results[1]


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_collect_requires_ai_configuration(cli, lang):
    cli.parity("--collect", "--lang", lang, exit_code=1)


@pytest.mark.parametrize(
    "date", ["2026-+1-15", "+026-1-15", "２０２６-1-15", "2026-1- 5", "2026115", "2026131", "20260230", "0001-1-1"]
)
def test_date_parser_contract(cli, date):
    args = ["--collect", "--dry-run", "--since", date, "--until", "2026-01-15", "-q", "provider:codex", "--lang", "en"]
    cli.parity(*args, exit_code=cli.run("python", *args).returncode)


def test_worker_log_failure_does_not_block_collect(cli):
    import shutil

    only_session(cli)
    results = []
    for candidate in ["python", "rust"]:
        path = cli.root / "logs" / "collect.jsonl"
        shutil.rmtree(path.parent, ignore_errors=True)

        def respond(body, count, path=path):
            if count == 1:
                path.unlink()
                path.mkdir()
            text = json.dumps({"requests": ["fact"]}) if "response_format" in body else "# Final"
            return 200, {"choices": [{"message": {"content": text}}]}

        with server(respond) as (url, _):
            configure(cli, url)
            config = config_path(cli)
            config.write_text(config.read_text().replace("enabled=false", 'enabled=true\npath="logs/collect.jsonl"'))
            result = cli.run(candidate, *ARGS, "--save", "report.md", "--lang", "en")
            assert result.returncode == 0, result.stdout + result.stderr
            results.append((result.stdout, result.stderr))
    assert results[0] == results[1]


def test_structured_retry_log_records(cli):
    import os

    only_session(cli)
    records = []
    for candidate in ["python", "rust"]:
        path = cli.root / "collect.jsonl"
        path.unlink(missing_ok=True)

        def respond(body, count):
            text = (
                '{"unexpected": []}'
                if count == 1
                else (json.dumps({"requests": ["fact"]}) if "response_format" in body else "# Final")
            )
            return 200, {"choices": [{"message": {"content": text}}]}

        with server(respond) as (url, _):
            configure(cli, url)
            config = config_path(cli)
            config.write_text(config.read_text().replace("enabled=false", 'enabled=true\npath="collect.jsonl"'))
            result = cli.run(candidate, *ARGS, "--save", "report.md", "--lang", "en")
            assert result.returncode == 0, result.stdout + result.stderr
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            assert {row["event"] for row in rows} >= {"collect_run_start", "llm_parse_error", "collect_run_finish"}
            for row in rows:
                for key in ["timestamp", "run_id", "request_id"]:
                    row.pop(key, None)
            records.append(rows)
            assert "fixture-secret" not in path.read_text()
            if os.name != "nt":
                assert path.stat().st_mode & 0o777 == 0o600
    assert records[0] == records[1]
