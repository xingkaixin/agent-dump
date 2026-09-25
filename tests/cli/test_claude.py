"""Claude Code behavior through Python and Rust CLIs on isolated synthetic projects."""

import json
import shutil

from cli_fixture import IDENTITY, STAMP, provider_export, write_jsonl
import pytest


def event(role, content, *, identity="event", **fields):
    return {
        "type": role,
        "uuid": identity,
        "timestamp": STAMP,
        "cwd": "/workspace/claude",
        "version": "1.0",
        "message": {"role": role, "content": content},
        **fields,
    }


def tool(identity="call", name="Read", **fields):
    return {"type": "tool_use", "id": identity, "name": name, "input": {"path": "file.py"}, **fields}


def result(identity="call", content="contents", **fields):
    return {"type": "tool_result", "tool_use_id": identity, "content": content, **fields}


def create(cli, records, *, identity=IDENTITY, project="-workspace-claude"):
    return write_jsonl(cli.root / "sources" / "claude" / "projects" / project / f"{identity}.jsonl", records)


@pytest.mark.parametrize(
    "records",
    [
        [
            event("user", "Start"),
            event("assistant", [{"type": "thinking", "thinking": "Think"}, {"type": "text", "text": "Done"}]),
        ],
        [event("assistant", [{"type": "thinking", "thinking": "Same"}])] * 2,
        [event("assistant", [{"type": "text", "text": "Reading"}, tool()]), event("user", [result()])],
        [event("assistant", [{"type": "thinking", "thinking": "Thinking"}, tool(), {"type": "text", "text": "Done"}])],
        [
            event(
                "assistant",
                [
                    {"type": "text", "text": "A"},
                    {"type": "thinking", "thinking": "B"},
                    tool(),
                    {"type": "text", "text": "C"},
                ],
            )
        ],
        [event("assistant", [tool()]), event("user", [result()]), event("user", [result(content="more")])],
        [event("assistant", [tool(), tool("other", "Bash")]), event("user", [result("other"), result()])],
        [event("assistant", [tool(name="TodoWrite")]), event("user", [result(), {"type": "text", "text": "Keep"}])],
        [event("assistant", [tool(name="TodoWrite", identity="")]), event("user", [result(identity="")])],
        [
            event("assistant", [tool()], identity="owner"),
            event("user", [result(identity="")], sourceToolAssistantUUID="owner"),
        ],
        [
            event("assistant", [tool(), tool("other")], identity="owner"),
            event("user", [result(identity="")], sourceToolAssistantUUID="owner"),
        ],
        [
            event("assistant", [tool(name="Skill")]),
            event("user", [result(content=[])], toolUseResult={"success": True, "commandName": "review"}),
        ],
        [event("assistant", [tool()]), event("user", [result()], toolUseResult={"success": False})],
        [event("user", [result("missing"), "ordinary text"]), event("tool_result", [{"content": "legacy"}])],
        [
            event("assistant", [{"type": "text", "text": "Ignore"}], isMeta=True),
            event("user", "Ignore", isMeta=True),
            event("user", "Keep"),
        ],
        [
            event("assistant", [{"type": "text", "text": "A"}]),
            event("user", "   "),
            event("assistant", [{"type": "text", "text": "B"}]),
        ],
        [
            event("assistant", [{"type": "text", "text": "A"}]),
            event("user", []),
            event("assistant", [{"type": "text", "text": "B"}]),
        ],
        [
            event("assistant", "ignored"),
            event("user", ["Keep", None, {"type": "image", "source": "ignored"}]),
            {"type": "system", "message": {"content": "ignored"}},
        ],
    ],
)
def test_transcript_streams(cli, records):
    create(cli, records)
    provider_export(cli, f"claude://{IDENTITY}", "claudecode")


@pytest.mark.parametrize(
    "content", [None, "", "  text  ", False, 1e-6, {"z": 2, "a": 1}, ["one", {"text": "two"}, {"content": 3}, None]]
)
def test_tool_output_shapes(cli, content):
    create(
        cli,
        [
            event("assistant", [tool()]),
            event("user", [result(content=content)]),
            event("user", [result("orphan", content)]),
        ],
    )
    provider_export(cli, f"claude://{IDENTITY}", "claudecode")


@pytest.mark.parametrize(
    "usage", [{"input_tokens": "17", "output_tokens": 4}, {"input_tokens": True, "output_tokens": "bad"}, [], None]
)
def test_grouped_usage_and_first_metadata(cli, usage):
    first = event("assistant", [{"type": "thinking", "thinking": "Think"}])
    second = event("assistant", [{"type": "text", "text": "Text"}, tool()])
    third = event("assistant", [{"type": "text", "text": "After tool"}])
    first["message"].update(model="first", usage=usage)
    second["message"].update(model="second", usage={"input_tokens": 100, "output_tokens": 2})
    third["message"].update(model="third", usage={"input_tokens": 3, "output_tokens": 5})
    create(cli, [first, second, third])
    provider_export(cli, f"claude://{IDENTITY}", "claudecode")


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("title_source", ["index", "message", "directory", "project"])
def test_discovery_titles_head_list_and_export(cli, lang, title_source):
    first = event("user", ["First", {"type": "text", "text": "中文"}])
    if title_source in ("directory", "project"):
        first["message"]["content"] = ""
    if title_source == "project":
        first.pop("cwd")
    path = create(
        cli, [first, event("assistant", [{"type": "text", "text": "Reply"}], timestamp="2026-01-15T12:00:01Z")]
    )
    if title_source == "index":
        path.with_name("sessions-index.json").write_text(
            json.dumps(
                {
                    "entries": [
                        {"sessionId": IDENTITY, "summary": "Old"},
                        {"sessionId": IDENTITY, "summary": " New\n标题 "},
                    ]
                }
            )
        )
    cli.parity("--list", "-d", "36500", "-q", "provider:claudecode", "--lang", lang)
    cli.parity("--list", "-d", "36500", "-q", "provider:claudecode", "--no-metadata-summary", "--lang", lang)
    cli.parity(f"claude://{IDENTITY}", "--head", "--lang", lang)
    provider_export(cli, f"claude://{IDENTITY}", "claudecode", lang=lang)


@pytest.mark.parametrize("layout", ["default-home", "local-fallback"])
def test_discovery_root_resolution(cli, layout):
    create(cli, [event("user", "Start")])
    target = cli.root / ("home/.claude/projects" if layout == "default-home" else "data/claudecode")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cli.root / "sources/claude/projects"), target)
    if layout == "default-home":
        cli.environment.pop("CLAUDE_CONFIG_DIR")
    cli.parity(f"claude://{IDENTITY}", "--head", "--lang", "en")


@pytest.mark.parametrize("oversized_header", [False, True])
def test_large_file_bounded_head(cli, oversized_header):
    records = [event("user", "Start"), event("assistant", [{"type": "text", "text": "文" * 350_000}])]
    if oversized_header:
        records[0]["padding"] = "x" * 300_000
    create(cli, records)
    cli.parity(f"claude://{IDENTITY}", "--head", "--lang", "en")
    provider_export(cli, f"claude://{IDENTITY}", "claudecode")


def test_discovery_date_order_and_project_depth(cli):
    create(cli, [event("user", "Older", timestamp="2026-01-14T12:00:00+00:00")], identity="older")
    create(cli, [event("user", "Current")])
    write_jsonl(cli.root / "sources/claude/projects/root.jsonl", [event("user", "Outside project")])
    write_jsonl(cli.root / "sources/claude/projects/project/subagents/nested.jsonl", [event("user", "Nested")])
    cli.parity("--list", "-d", "36500", "-q", "provider:claudecode", "--lang", "en")
    cli.parity("--list", "-d", "1", "-q", "provider:claudecode", "--lang", "en")


def test_exports_cannot_write_into_claude_sources(cli):
    create(cli, [event("user", "Start")])
    before = cli.fixtures.source_manifest(cli.root)
    result_ = cli.run(
        "rust", f"claude://{IDENTITY}", "--format", "json,md,raw", "--output", str(cli.root / "sources/claude")
    )
    assert result_.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before
