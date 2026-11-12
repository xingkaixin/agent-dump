"""Antigravity CLI conversation databases through the published CLI surface."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from cli_fixture import IDENTITY
import pytest

STAMP = 1768478400


def encode(value):
    output = bytearray()
    while value >= 0x80:
        output.append(value & 0x7F | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def varint(number, value):
    return encode(number << 3) + encode(value)


def field(number, value):
    value = value.encode() if isinstance(value, str) else value
    return encode(number << 3 | 2) + encode(len(value)) + value


def metadata(created=None, call=None, usage=None, model=None):
    body = b""
    if created is not None:
        body += field(1, varint(1, created))
    if call is not None:
        body += field(4, call)
    if usage is not None:
        body += field(9, usage)
    if model is not None:
        body += field(24, model)
    return field(5, body)


def user(text, created=STAMP):
    return 14, field(19, field(2, text)) + metadata(created)


def assistant(text, created=STAMP, usage=None, model=None):
    return 15, field(20, field(1, text)) + metadata(created, usage=usage, model=model)


def create(cli, steps, *, identity=IDENTITY, conversations=None, summary=None, models=(), workspace_uris=None):
    conversations = conversations or cli.root / "sources/antigravity-cli/conversations"
    conversations.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(conversations / f"{identity}.db")
    connection.executescript(
        "CREATE TABLE steps (idx INTEGER PRIMARY KEY, step_type INTEGER NOT NULL, status INTEGER NOT NULL,"
        " step_payload BLOB); CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB);"
    )
    connection.executemany(
        "INSERT INTO steps VALUES (?, ?, 3, ?)", [(index, kind, payload) for index, (kind, payload) in enumerate(steps)]
    )
    connection.executemany(
        "INSERT INTO gen_metadata (data) VALUES (?)",
        [(field(1, varint(3, model_id) + field(19, model)),) for model_id, model in models],
    )
    if workspace_uris is not None:
        connection.execute("CREATE TABLE trajectory_metadata_blob (data BLOB)")
        connection.execute(
            "INSERT INTO trajectory_metadata_blob VALUES (?)",
            (b"".join(field(7, uri) for uri in workspace_uris),),
        )
    connection.commit()
    connection.close()
    if summary is not None:
        connection = sqlite3.connect(conversations.parent / "conversation_summaries.db")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS conversation_summaries (conversation_id TEXT PRIMARY KEY, title TEXT,"
            " workspace_uris TEXT, last_modified_time TEXT, parent_conversation_id TEXT)"
        )
        connection.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, '')",
            (identity, summary.get("title", ""), json.dumps(summary.get("workspaces", [])), summary.get("modified")),
        )
        connection.commit()
        connection.close()
    return conversations / f"{identity}.db"


def run_json(cli, *args):
    result = cli.run(*args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def listed(cli):
    return {item["id"]: item for item in run_json(cli, "--list", "-d", "36500", "-q", "provider:antigravity-cli")}


def test_list_head_and_export(cli):
    workspace = Path(cli.root / "workspace").resolve()
    usage = varint(1, 7) + varint(2, 10) + varint(3, 6) + varint(5, 2) + varint(9, 2) + field(11, "response")
    call = field(1, "call-1") + field(2, "read_file") + field(3, '{"path": "a.rs"}')
    create(
        cli,
        [
            user("<system-reminder>hidden</system-reminder>\nFix   the bug\nmore"),
            (15, metadata(STAMP + 1, usage=usage)),
            (132, metadata(call=call)),
            assistant("Done", STAMP + 2),
            (23, field(30, field(4, "Native title"))),
            (999, varint(100, 1)),
        ],
        summary={
            "title": "Summary title",
            "workspaces": [workspace.as_uri()],
            "modified": "2026-01-15 12:01:40.000000+00:00",
        },
        models=[(7, "gemini-3-pro")],
    )
    before = cli.fixtures.source_manifest(cli.root)

    record = listed(cli)[IDENTITY]
    assert {key: record[key] for key in ("title", "created_at", "model", "message_count", "working_directory")} == {
        "title": "Native title",
        "created_at": "2026-01-15T12:00:00.000000+00:00",
        "model": "gemini-3-pro",
        "message_count": 3,
        "working_directory": str(workspace),
    }
    head = run_json(cli, f"antigravity-cli://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record

    result = cli.run(f"antigravity-cli://{IDENTITY}", "--format", "json,md", "--output", "exports")
    assert result.returncode == 0, result.stderr
    exports = cli.root / "exports/antigravity-cli"
    assert "Fix   the bug" in (exports / f"{IDENTITY}.md").read_text()
    payload = json.loads((exports / f"{IDENTITY}.json").read_text())
    assert cli.fixtures.source_manifest(cli.root) == before

    assert payload["stats"] == {
        "total_cost": 0,
        "total_input_tokens": 12,
        "total_output_tokens": 6,
        "message_count": 3,
        "total_tokens": 18,
    }
    prompt, tool, answer = payload["messages"]
    assert [part["text"] for part in prompt["parts"]] == ["Fix   the bug\nmore"]
    assert (tool["role"], tool["model"], tool["inferred_time"]) == ("assistant", "gemini-3-pro", True)
    assert tool["time_created"] == (STAMP + 100) * 1000
    assert tool["tokens"] == {"input": 12, "output": 4, "reasoning": 2, "cache": {"read": 2, "write": 0}}
    (part,) = tool["parts"]
    assert (part["tool"], part["callID"], part["state"]["status"], part["state"]["input"]) == (
        "read_file",
        "call-1",
        "unknown",
        {"path": "a.rs"},
    )
    assert (answer["agent"], answer["parts"][0]["text"], "inferred_time" in answer) == (
        "antigravity-cli",
        "Done",
        False,
    )


def test_default_root_override_and_empty_databases(cli):
    home = Path(cli.environment["HOME"])
    create(
        cli,
        [user("Isolated prompt")],
        identity="isolated",
        conversations=home / ".t3/userdata/providers/antigravity/account/antigravity-acp/conversations",
    )
    create(
        cli,
        [user("Default prompt")],
        identity="default",
        conversations=home / ".gemini/antigravity-cli/conversations",
        summary={"title": "Default title"},
    )
    create(cli, [user("Override prompt")], identity="override")
    create(cli, [], identity="empty")

    assert {key: item["title"] for key, item in listed(cli).items()} == {"override": "Override prompt"}
    missing = cli.run("antigravity-cli://empty", "--head")
    assert missing.returncode == 1

    del cli.environment["AGY_CONVERSATIONS_DIR"]
    assert {key: item["title"] for key, item in listed(cli).items()} == {
        "default": "Default title",
        "isolated": "Isolated prompt",
    }


@pytest.mark.parametrize("summary_mode", ["missing", "empty", "present"])
def test_workspace_and_step_model_fallbacks(cli, summary_mode):
    workspace = cli.root / "workspace"
    summary_workspace = cli.root / "summary-workspace"
    summary = None
    if summary_mode != "missing":
        summary = {"workspaces": [summary_workspace.as_uri()] if summary_mode == "present" else []}
    create(
        cli,
        [
            user("ACP prompt"),
            assistant(
                "ACP answer",
                usage=varint(2, 10) + varint(3, 6),
                model=field(8, "Display model") + field(12, "api-model"),
            ),
        ],
        summary=summary,
        workspace_uris=["https://example.test/remote", workspace.as_uri()],
    )
    before = cli.fixtures.source_manifest(cli.root)
    expected_directory = str(summary_workspace if summary_mode == "present" else workspace)
    record = listed(cli)[IDENTITY]
    assert (record["working_directory"], record["model"], record["message_count"]) == (
        expected_directory,
        "api-model",
        2,
    )
    head = run_json(cli, f"antigravity-cli://{IDENTITY}", "--head")
    assert {key: head[key] for key in record} == record
    result = cli.run(f"antigravity-cli://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    payload = json.loads((cli.root / f"exports/antigravity-cli/{IDENTITY}.json").read_text())
    assert (payload["directory"], payload["messages"][1]["model"], payload["stats"]["total_tokens"]) == (
        expected_directory,
        "api-model",
        16,
    )
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("custom_home", [False, True])
def test_isolated_profiles_are_discovered_with_native_history(cli, custom_home):
    del cli.environment["AGY_CONVERSATIONS_DIR"]
    home = Path(cli.environment["HOME"])
    t3_home = home / ("custom-t3" if custom_home else ".t3")
    if custom_home:
        cli.environment["T3CODE_HOME"] = " ~/custom-t3 "
        create(
            cli,
            [user("Unselected home")],
            identity="unselected",
            conversations=home / ".t3/userdata/providers/antigravity/ignored/antigravity-acp/conversations",
        )
    profiles = t3_home / "userdata/providers/antigravity"
    workspace = cli.root / "workspace"
    for identity in ["first", "second"]:
        create(
            cli,
            [user(f"{identity} prompt")],
            identity=identity,
            conversations=profiles / identity / "antigravity-acp/conversations",
            summary={"title": f"{identity} title", "workspaces": [workspace.as_uri()]},
        )
    (profiles / "first/unrelated.db").write_bytes(b"not a conversation")
    records = listed(cli)
    assert {key: item["title"] for key, item in records.items()} == {
        "first": "first title",
        "second": "second title",
    }
    for identity, record in records.items():
        head = run_json(cli, f"antigravity-cli://{identity}", "--head")
        assert {key: head[key] for key in record} == record
        assert record["working_directory"] == str(workspace)
    create(
        cli,
        [user("Native prompt")],
        identity="native",
        conversations=home / ".gemini/antigravity-cli/conversations",
    )
    assert set(listed(cli)) == {"native", "first", "second"}
    providers = run_json(cli, "--providers")
    provider = next(item for item in providers if item["provider"] == "antigravity-cli")
    assert {"label": "T3CODE_HOME", "path": str(profiles), "exists": True} in provider["search_roots"]


@pytest.mark.parametrize("failure", ["session", "summary", "profiles"])
def test_isolated_source_failure_keeps_other_stores_visible(cli, failure):
    del cli.environment["AGY_CONVERSATIONS_DIR"]
    cli.environment["T3CODE_HOME"] = str(cli.root / "sources/t3")
    profiles = cli.root / "sources/t3/userdata/providers/antigravity"
    create(
        cli,
        [user("Native prompt")],
        identity="native",
        conversations=Path(cli.environment["HOME"]) / ".gemini/antigravity-cli/conversations",
    )
    expected = {"native"}
    if failure == "profiles":
        profiles.parent.mkdir(parents=True)
        profiles.write_bytes(b"not a directory")
        broken = profiles
    else:
        create(
            cli,
            [user("Healthy isolated prompt")],
            identity="healthy",
            conversations=profiles / "healthy/antigravity-acp/conversations",
        )
        expected.add("healthy")
        broken = create(
            cli,
            [user("Broken isolated prompt")],
            identity="broken",
            conversations=profiles / "broken/antigravity-acp/conversations",
        )
        if failure == "summary":
            broken = broken.parent.parent / "conversation_summaries.db"
        broken.write_bytes(b"not a database")
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run("--list", "--json", "-d", "36500", "-q", "provider:antigravity-cli", "--lang", "en")
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "partial"
    assert document["failed_providers"] == ["antigravity-cli"]
    assert {item["id"] for item in document["data"]} == expected
    assert str(broken.parent if failure == "summary" else broken) in result.stderr
    for identity in expected:
        assert run_json(cli, f"antigravity-cli://{identity}", "--head")["id"] == identity
    assert cli.fixtures.source_manifest(cli.root) == before


@pytest.mark.parametrize("target", ["native", "first", "second"])
def test_all_antigravity_stores_are_protected_from_output(cli, target):
    del cli.environment["AGY_CONVERSATIONS_DIR"]
    cli.environment["T3CODE_HOME"] = str(cli.root / "sources/t3")
    stores = {"native": Path(cli.environment["HOME"]) / ".gemini/antigravity-cli/conversations"}
    for identity in ["first", "second"]:
        stores[identity] = (
            cli.root / f"sources/t3/userdata/providers/antigravity/{identity}/antigravity-acp/conversations"
        )
    for identity, conversations in stores.items():
        create(cli, [user("Protected prompt")], identity=identity, conversations=conversations)
    before = {
        path: path.read_bytes() for store in stores.values() for path in store.parent.rglob("*") if path.is_file()
    }
    output = stores[target].parent / "output"
    result = cli.run(f"codex://{IDENTITY}", "--format", "json", "--output", str(output), "--lang", "en")
    assert result.returncode == 1
    assert "Export output must be outside the Provider source directory" in result.stdout
    assert not output.exists()
    cli.environment["XDG_CACHE_HOME"] = str(output)
    result = cli.run("--search", "Protected", "--json", "-d", "36500", "-q", "provider:antigravity-cli", "--lang", "en")
    assert result.returncode == 0, result.stderr
    assert {item["id"] for item in json.loads(result.stdout)["data"]} == set(stores)
    assert "falling back to a file scan" in result.stderr
    assert not output.exists()
    assert all(path.read_bytes() == contents for path, contents in before.items())


def test_isolated_wal_updates_refresh_search(cli):
    del cli.environment["AGY_CONVERSATIONS_DIR"]
    conversations = (
        Path(cli.environment["HOME"]) / ".t3/userdata/providers/antigravity/account/antigravity-acp/conversations"
    )
    database = create(cli, [user("Original prompt"), assistant("before-needle")], conversations=conversations)
    args = ("--json", "-d", "36500", "-q", "provider:antigravity-cli")
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert len(run_json(cli, "--search", "before-needle", *args)) == 1
        original = database.read_bytes()
        writer.execute("UPDATE steps SET step_payload = ? WHERE idx = 1", (assistant("after-needle")[1],))
        writer.commit()
        assert database.read_bytes() == original
        durable = {
            path: path.read_bytes()
            for path in conversations.iterdir()
            if path.is_file() and not path.name.endswith("-shm")
        }
        assert [item["id"] for item in run_json(cli, "--search", "after-needle", *args)] == [IDENTITY]
        assert run_json(cli, "--search", "before-needle", *args) == []
        assert all(path.read_bytes() == contents for path, contents in durable.items())
