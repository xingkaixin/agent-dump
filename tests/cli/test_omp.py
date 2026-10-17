"""oh-my-pi sessions in the Pi session tree format."""

import json
import os

from cli_fixture import IDENTITY, STAMP, write_jsonl
from test_pi import message

STEM = f"2026-01-15T12-00-00-000Z_{IDENTITY}"


def create(sessions, identity, records, *, name=STEM):
    header = {"type": "session", "version": 3, "id": identity, "cwd": "/workspace/omp", "timestamp": STAMP}
    return write_jsonl(sessions / "--workspace-omp--" / f"{name}.jsonl", [header, *records])


def listed(cli):
    listing = cli.run("rust", "--list", "-d", "36500", "-q", "provider:omp", "--json")
    assert listing.returncode == 0, listing.stderr
    return {item["id"]: item for item in json.loads(listing.stdout)["data"]}


def test_list_and_export_use_the_pi_session_tree(cli):
    sessions = cli.root / "home/.omp/agent/sessions"
    usage = {"input": 100, "output": 50, "cacheRead": 1000, "cacheWrite": 200, "totalTokens": 1350}
    source = create(
        sessions,
        IDENTITY,
        [
            {"type": "title", "title": "Port the parser to omp"},
            message("user", "Port the parser", identity="prompt"),
            message(
                "assistant",
                [{"type": "toolCall", "id": "call", "name": "task", "arguments": {"agent": "explore"}}],
                identity="call-owner",
                parent="prompt",
                model="claude-opus-5-5",
                usage=usage,
            ),
            message("toolResult", "done", identity="output", parent="call-owner", toolCallId="call"),
        ],
    )
    create(sessions, "explore", [message("user", "Find the parser")], name=f"{STEM}/0-Explore")
    before = source.read_bytes()

    sessions = listed(cli)
    assert {key: item["title"] for key, item in sessions.items()} == {
        IDENTITY: "Port the parser to omp",
        "explore": "Find the parser",
    }
    record = sessions[IDENTITY]
    assert (record["uri"], record["working_directory"], record["message_count"]) == (
        f"omp://{IDENTITY}",
        "/workspace/omp",
        2,
    )

    exported = cli.run("rust", record["uri"], "--format", "json,raw", "--output", "exports")
    assert exported.returncode == 0, exported.stderr
    exports = cli.root / "exports/omp"
    assert (exports / f"{IDENTITY}.raw.jsonl").read_bytes() == source.read_bytes() == before
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert payload["stats"]["total_input_tokens"] == 1300
    user, assistant = payload["messages"]
    assert user["parts"][0]["text"] == "Port the parser"
    assert (assistant["agent"], assistant["model"]) == ("omp", "claude-opus-5-5")
    assert assistant["parts"][0]["state"]["status"] == "completed"


def test_xdg_data_directory_replaces_home_outside_windows(cli):
    create(cli.root / "home/.omp/agent/sessions", "home", [message("user", "Home")])
    create(cli.root / "data/omp/sessions", "xdg", [message("user", "XDG")])

    assert list(listed(cli)) == ["home" if os.name == "nt" else "xdg"]
