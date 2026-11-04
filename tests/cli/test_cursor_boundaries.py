"""Cursor discovery and transcript rules asserted on the Rust CLI."""

import json

from test_cursor import cursor


def run_json(cli, *args):
    result = cli.run(*args, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)["data"]


def export(cli, uri):
    result = cli.run(uri, "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(next((cli.root / "exports/cursor").glob("*.json")).read_text())


def test_legacy_request_uri_finds_composer_session(tmp_path, monkeypatch):
    cli = cursor(tmp_path, monkeypatch)
    legacy = run_json(cli, "cursor://request-parent", "--head")
    assert legacy == run_json(cli, "cursor://parent", "--head")
    assert legacy["uri"] == "cursor://parent"
    data = export(cli, "cursor://request-parent")
    assert data["id"] == "parent"
    assert [part["text"] for item in data["messages"] for part in item["parts"]] == ["prompt", "answer"]
