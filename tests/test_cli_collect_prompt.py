"""Collect prompt generation through normal CLI and shortcut entry points."""

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from unittest import mock

from cli_test_support import configure_session_data_lease, make_session
from locale_helpers import Keys, expect, expect_contains
import pytest

from agent_dump.agents.base import BaseAgent
from agent_dump.cli import main
from agent_dump.collect_handoff import MANIFEST_END_MARKER
from agent_dump.collect_sessions import collect_entries
from agent_dump.command_plan import CollectOperation, CommandRequest, build_command_plan
from agent_dump.config import CollectConfig, ConfigurationParseError, ShortcutConfig, get_config_path


def _prompt_records(prompt: str) -> list[dict[str, Any]]:
    return [json.loads(json.loads(line)["content"]) for line in prompt.splitlines() if line.startswith("{")]


def test_large_shortcut_prompt_is_complete_when_stdout_is_saved_directly(
    codex_session_tree: dict[str, object], tmp_path: Path
) -> None:
    source_path = Path(str(codex_session_tree["session_file"]))
    original = source_path.read_text(encoding="utf-8")
    original_id = str(codex_session_tree["session_id"])
    session_ids = {original_id}
    for index in range(208):
        identity = f"019c213e-c251-73a3-af66-{index:012x}"
        source_path.with_name(source_path.name.replace(original_id, identity)).write_text(
            original.replace(original_id, identity), encoding="utf-8"
        )
        session_ids.add(identity)
    config = get_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        '[shortcut.daily]\nparams = ["date"]\nargs = ["--collect", "--since", "{date}", "--until", "{date}"]\n',
        encoding="utf-8",
    )
    report_path = tmp_path / "report.md"
    task_dir = tmp_path / "handoff"
    task_dir.mkdir(mode=0o700)
    prompt_path = task_dir / "prompt.md"
    diagnostics_path = task_dir / "diagnostics.txt"
    argv = [
        sys.executable,
        "-m",
        "agent_dump",
        "--shortcut",
        "daily",
        "20260720",
        "--emit-prompt",
        "--save",
        str(report_path),
        "--lang",
        "zh",
    ]

    with prompt_path.open("w", encoding="utf-8") as stdout, diagnostics_path.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(  # noqa: S603 - Runs the CLI only against isolated provider fixtures.
            argv, cwd=tmp_path, stdout=stdout, stderr=stderr, timeout=30
        )

    assert result.returncode == 0, diagnostics_path.read_text(encoding="utf-8")
    prompt = prompt_path.read_text(encoding="utf-8")
    context, *entries = _prompt_records(prompt)
    assert context["session_count"] == len(entries) == 209
    assert context["report_path"] == str(report_path)
    assert {entry["uri"] for entry in entries} == {f"codex://{identity}" for identity in session_ids}
    assert all(entry["read_argv"][-3:] == [entry["uri"], "--format", "print"] for entry in entries)
    envelopes = [json.loads(line) for line in prompt.splitlines() if line.startswith("{")]
    assert all(envelope["length"] == len(envelope["content"]) for envelope in envelopes)
    assert all(envelope["source"] == entry["uri"] for envelope, entry in zip(envelopes[1:], entries, strict=True))
    assert prompt.splitlines()[-1] == MANIFEST_END_MARKER
    assert prompt.splitlines().count(MANIFEST_END_MARKER) == 1
    assert expect(Keys.COLLECT_PROGRESS_START, since="2026-07-20", until="2026-07-20") not in prompt
    assert expect_contains(
        diagnostics_path.read_text(encoding="utf-8"),
        Keys.COLLECT_PROGRESS_START,
        since="2026-07-20",
        until="2026-07-20",
    )
    assert not report_path.exists()
    assert source_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("entry_point", ["direct", "shortcut_args", "shortcut_trailing"])
def test_prompt_needs_no_api_and_its_command_reads_the_selected_session(
    entry_point: str,
    codex_session_tree: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "reports" / "report-20260720.md"
    config_path = tmp_path / "missing-config.toml"
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: config_path)
    monkeypatch.setattr("agent_dump.collect_workflow.get_local_timezone", lambda: timezone.utc)
    if entry_point == "direct":
        argv = ["--collect", "--emit-prompt", "--since", "20260720", "--until", "20260720", "--save", str(output)]
    else:
        preset = ShortcutConfig(
            params=("date",),
            args=(
                "--collect",
                "--since",
                "{date}",
                "--until",
                "{date}",
                "--save",
                str(output.parent / "report-{date}.md"),
                *(["--emit-prompt"] if entry_point == "shortcut_args" else []),
            ),
        )
        monkeypatch.setattr("agent_dump.cli.load_shortcuts_config", lambda: {"daily": preset})
        argv = ["--shortcut", "daily", "20260720", *(["--emit-prompt"] if entry_point == "shortcut_trailing" else [])]
    monkeypatch.setattr("sys.argv", ["agent-dump", *argv])
    source_path = Path(str(codex_session_tree["session_file"]))
    original = source_path.read_bytes()
    with (
        mock.patch("agent_dump.config.ConfigurationDocument.ai_config") as ai_config,
        mock.patch("agent_dump.collect_workflow.create_collect_logger") as logger,
        mock.patch("agent_dump.collect_workflow.collect_entries") as entries,
        mock.patch("agent_dump.collect_workflow.plan_collect_entries") as chunks,
        mock.patch("agent_dump.agents.codex.CodexAgent.get_session_data") as transcript,
        mock.patch("agent_dump.cli.request_summary_from_llm") as final_request,
        mock.patch("agent_dump.cli.request_structured_summary_from_llm") as structured_request,
        mock.patch("agent_dump.collect_workflow.write_collect_markdown") as write_report,
    ):
        assert main() == 0

    for unused in (ai_config, logger, entries, chunks, transcript, final_request, structured_request, write_report):
        unused.assert_not_called()
    captured = capsys.readouterr()
    context, entry = _prompt_records(captured.out)
    assert context["session_count"] == 1
    assert context["report_path"] == str(output)
    assert context["working_directory"] == str(tmp_path)
    assert entry["uri"] == f"codex://{codex_session_tree['session_id']}"
    assert str(codex_session_tree["user_text"]) not in captured.out
    assert not output.parent.exists()
    assert not config_path.exists()
    read_result = subprocess.run(  # noqa: S603 - Executes only the generated argv against isolated fixture data.
        entry["read_argv"],
        cwd=context["working_directory"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert read_result.returncode == 0, read_result.stderr
    assert str(codex_session_tree["user_text"]) in read_result.stdout
    assert str(codex_session_tree["assistant_text"]) in read_result.stdout
    assert source_path.read_bytes() == original


def test_prompt_applies_the_same_date_deny_path_provider_role_keyword_and_limit_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    denied = project / "private"
    created = datetime(2026, 8, 30, 18, tzinfo=timezone.utc)
    local_tz = timezone(timedelta(hours=8))
    sessions = [
        make_session(identity, identity, created_at=created + timedelta(hours=hours), metadata={"cwd": str(cwd)})
        for identity, hours, cwd in [
            ("older", 0, project),
            ("newer", 1, project),
            ("denied", 2, denied),
            ("outside-path", 2, tmp_path / "other-project"),
            ("outside-date", -12, project),
            ("wrong-role", 3, project),
        ]
    ]
    agent = mock.MagicMock(spec=BaseAgent)
    agent.name = "codex"
    agent.display_name = "Codex"
    agent.get_session_uri.side_effect = lambda session: f"codex://{session.id}"
    configure_session_data_lease(agent)
    agent.get_cached_session_data.side_effect = lambda session: {
        "messages": [
            {
                "role": "assistant" if session.id == "wrong-role" else "user",
                "parts": [{"type": "text", "text": "match sensitive transcript text"}],
            }
        ]
    }
    other_agent = mock.MagicMock(spec=BaseAgent)
    other_agent.name = "kimi"
    groups = [(agent, sessions), (other_agent, [sessions[1]])]
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[agent.codex]\ndeny = {json.dumps([str(denied)])}\n", encoding="utf-8")
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: config_path)
    monkeypatch.setattr("agent_dump.collect_workflow.get_local_timezone", lambda: local_tz)
    scanner = mock.MagicMock()
    scanner.get_available_sessions.return_value = groups
    monkeypatch.setattr("agent_dump.cli.AgentScanner", lambda: scanner)
    uri = f"agents://{project.as_posix()}?providers=codex&roles=user&q=match&limit=1"
    monkeypatch.setattr(
        "sys.argv", ["agent-dump", "--collect", "--emit-prompt", uri, "--since", "20260831", "--until", "20260831"]
    )

    assert main() == 0

    output = capsys.readouterr().out
    context, selected = _prompt_records(output)
    assert context["session_count"] == 1
    assert selected["uri"] == "codex://newer"
    assert selected["date"] == "2026-08-31"
    assert "sensitive transcript text" not in output
    operation = build_command_plan(CommandRequest(collect=True, uri=uri)).operation
    assert isinstance(operation, CollectOperation)
    regular_entries = collect_entries(
        session_groups=groups,
        since_date=date(2026, 8, 31),
        until_date=date(2026, 8, 31),
        collect_config=CollectConfig(agent_denies={"codex": (str(denied),)}),
        query_spec=operation.query_spec,
        local_tz=local_tz,
    )
    assert [entry.session_uri for entry in regular_entries] == [selected["uri"]]
    other_agent.get_cached_session_data.assert_not_called()


@pytest.mark.parametrize("has_provider", [False, True])
def test_empty_prompt_result_writes_only_a_diagnostic(
    has_provider: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: tmp_path / "missing.toml")
    scanner = mock.MagicMock()
    scanner.get_available_sessions.return_value = [(mock.MagicMock(), [])] if has_provider else []
    monkeypatch.setattr("agent_dump.cli.AgentScanner", lambda: scanner)
    monkeypatch.setattr(
        "sys.argv", ["agent-dump", "--collect", "--emit-prompt", "--since", "20260831", "--until", "20260831"]
    )

    assert main() == (0 if has_provider else 1)

    captured = capsys.readouterr()
    assert captured.out == ""
    expected = (
        expect(Keys.COLLECT_NO_SESSIONS, since="2026-08-31", until="2026-08-31")
        if has_provider
        else expect(Keys.NO_AGENTS_FOUND)
    )
    assert expected in captured.err


@pytest.mark.parametrize("since", ["bad-date", "20260901"])
def test_prompt_date_errors_stop_before_discovery(
    since: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["agent-dump", "--collect", "--emit-prompt", "--since", since, "--until", "20260831"]
    )
    with mock.patch("agent_dump.cli.AgentScanner") as scanner:
        assert main() == 1

    scanner.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    key = Keys.COLLECT_DATE_FORMAT_INVALID if since == "bad-date" else Keys.COLLECT_DATE_RANGE_INVALID
    assert expect(key) in captured.err


def test_prompt_discovery_failure_does_not_emit_partial_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr("sys.argv", ["agent-dump", "--collect", "--emit-prompt"])
    scanner = mock.MagicMock()
    scanner.get_available_sessions.side_effect = OSError("cannot discover")
    monkeypatch.setattr("agent_dump.cli.AgentScanner", lambda: scanner)

    assert main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert expect_contains(captured.err, Keys.COLLECT_READ_FAILED, error="cannot discover")


def test_prompt_unreadable_configuration_does_not_pollute_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["agent-dump", "--collect", "--emit-prompt"])
    with (
        mock.patch(
            "agent_dump.collect_workflow.load_config_document", side_effect=PermissionError("config unreadable")
        ),
        mock.patch("agent_dump.cli.AgentScanner") as scanner,
    ):
        assert main() == 1

    captured = capsys.readouterr()
    scanner.assert_not_called()
    assert captured.out == ""
    assert "config unreadable" in captured.err


@pytest.mark.parametrize("invalid_config", [False, True])
def test_prompt_shortcut_errors_do_not_pollute_stdout(
    invalid_config: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["agent-dump", "--shortcut", "unknown", "--emit-prompt"])
    with mock.patch(
        "agent_dump.cli.load_shortcuts_config",
        return_value={},
        side_effect=ConfigurationParseError(tmp_path / "config.toml") if invalid_config else None,
    ):
        assert main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_prompt_keeps_existing_reports_and_routes_ignored_option_warnings_to_stderr(
    codex_session_tree: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "existing.md"
    report.write_text("existing report", encoding="utf-8")
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: tmp_path / "missing.toml")
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-dump",
            "--collect",
            "--emit-prompt",
            "--since",
            "20260720",
            "--until",
            "20260721",
            "--save",
            str(report),
            "--summary",
            "--stats",
        ],
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert report.read_text(encoding="utf-8") == "existing report"
    assert expect(Keys.SUMMARY_IGNORED_NON_URI_WARNING) in captured.err
    assert expect(Keys.SUMMARY_IGNORED_NON_URI_WARNING) not in captured.out
    assert expect_contains(captured.err, Keys.CLI_MODE_OPTIONS_IGNORED_WARNING, options="--stats")
    assert _prompt_records(captured.out)[0]["report_path"] == str(report)
