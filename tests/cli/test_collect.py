"""Collect contracts exercised through both CLIs and a local HTTP endpoint."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
from test_config_shortcuts import config_path

pytestmark = pytest.mark.differential

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
@pytest.mark.parametrize(
    "dates",
    [
        ["--since", "bad"],
        ["--since", "2026-02-01", "--until", "2026-01-01"],
    ],
)
def test_date_ranges(cli, lang, dates):
    only_session(cli)
    args = ["--collect", "--dry-run", "-q", "provider:codex", "--lang", lang, *dates]
    result = cli.run("python", *args)
    cli.parity(*args, exit_code=result.returncode)


def only_session(cli):
    for path in (cli.root / "sources" / "codex" / "sessions").rglob("*.jsonl"):
        if path != cli.source:
            path.unlink()


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "config",
    [
        'bad = "unterminated',
        "[agent.codex]\ndeny=42\n",
        "[agent]\ncodex=42\n",
        "[agent.codex]\ndeny=[0]\n",
        '[agent.codex]\ndeny=[""]\n',
    ],
)
def test_collect_config_validation(cli, lang, config):
    only_session(cli)
    config_path(cli).write_text(config)
    args = [*ARGS, "--dry-run", "--lang", lang]
    expected = cli.run("python", *args).returncode
    cli.parity(*args, exit_code=expected)


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


@pytest.mark.parametrize("date", ["2026-+1-15", "+026-1-15", "2026115", "2026131", "20260230"])
def test_date_parser_contract(cli, date):
    only_session(cli)
    args = ["--collect", "--dry-run", "--since", date, "--until", "2026-01-15", "-q", "provider:codex", "--lang", "en"]
    cli.parity(*args, exit_code=cli.run("python", *args).returncode)
