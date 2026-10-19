"""Collect and summary contracts exercised through a local HTTP endpoint."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from cli_fixture import IDENTITY
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


def only_session(cli):
    for path in (cli.root / "sources" / "codex" / "sessions").rglob("*.jsonl"):
        if path != cli.source:
            path.unlink()


@pytest.mark.parametrize(
    ("dates", "message"),
    [
        (["--since", "bad"], "❌ Invalid date format. Use YYYY-MM-DD or YYYYMMDD."),
        (["--since", "2026-+1-15", "--until", "2026-01-15"], "❌ Invalid date format. Use YYYY-MM-DD or YYYYMMDD."),
        (["--since", "20260230", "--until", "2026-01-15"], "❌ Invalid date format. Use YYYY-MM-DD or YYYYMMDD."),
        (["--since", "2026-02-01", "--until", "2026-01-01"], "❌ Invalid date range: since must be <= until."),
    ],
)
def test_invalid_date_ranges(cli, dates, message):
    only_session(cli)
    result = cli.run("rust", "--collect", "--dry-run", "-q", "provider:codex", "--lang", "en", *dates)
    assert (result.returncode, result.stdout, result.stderr) == (1, f"{message}\n", "")


@pytest.mark.parametrize(
    ("config", "field"),
    [
        ('bad = "unterminated', "TOML"),
        ("[agent.codex]\ndeny=42\n", "agent.codex.deny"),
        ("[agent]\ncodex=42\n", "agent.codex"),
        ("[agent.codex]\ndeny=[0]\n", "agent.codex.deny"),
        ('[agent.codex]\ndeny=[""]\n', "agent.codex.deny"),
    ],
)
def test_invalid_exclusion_config_stops_collect(cli, config, field):
    only_session(cli)
    config_path(cli).write_text(config)
    result = cli.run("rust", *ARGS, "--dry-run", "--lang", "en")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not result.stderr
    assert result.stdout == (
        f"❌ collect cannot safely use configuration field {field}; "
        "fix the TOML syntax and exclusion path arrays before retrying.\n"
    )


def test_collect_requires_ai_configuration(cli):
    result = cli.run("rust", "--collect", "--lang", "en")
    assert (result.returncode, result.stdout, result.stderr) == (
        1,
        "❌ Collect requires config file.\nRun: agent-dump -config edit\n",
        "",
    )


@pytest.mark.parametrize(
    ("scenario", "requests", "notice"),
    [
        ("success", 1, "✅ Applied summary to JSON: "),
        ("missing-config", 0, "⚠️  --summary skipped: config file not found."),
        ("incomplete-config", 0, "⚠️  --summary skipped: config missing fields: base_url,model,api_key"),
        ("401", 1, "⚠️  --summary skipped: AI summary request failed: OpenAI API HTTP 401"),
    ],
)
def test_uri_summary_failures_still_export(cli, scenario, requests, notice):
    def respond(body, count):
        return (401, {}) if scenario == "401" else (200, {"choices": [{"message": {"content": "# Summary"}}]})

    with server(respond) as (url, calls):
        configure(cli, url)
        if scenario == "missing-config":
            config_path(cli).unlink()
        if scenario == "incomplete-config":
            config_path(cli).write_text('[ai]\nprovider="openai"\n')
        result = cli.run(
            "rust", f"codex://{IDENTITY}", "--summary", "--format", "json", "--output", "exports", "--lang", "en"
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(notice)
    assert len(calls) == requests
    exported = (cli.root / "exports" / "codex" / f"{IDENTITY}.json").read_text()
    assert ("# Summary" in exported) == (scenario == "success")
