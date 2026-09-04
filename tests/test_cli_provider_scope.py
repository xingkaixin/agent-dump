"""Provider discovery scope through CLI parsing and workflow dispatch."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from locale_helpers import Keys, expect_contains
import pytest

from agent_dump.agents.base import BaseAgent, ProviderDiscovery, Session
from agent_dump.cli import main
from agent_dump.scanner import AgentScanner


class RecordingProvider(BaseAgent):
    def __init__(self, name: str, root: Path, *, available: bool = True) -> None:
        super().__init__(name, name.title())
        now = datetime.now(timezone.utc)
        self.session = Session(name, f"{name} work", now, now, root / name, {"cwd": str(root)})
        self.available = available
        self.discoveries = 0
        self.reads = 0

    def is_available(self) -> bool:
        raise AssertionError("discovery must own availability")

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        return list(self.discover_sessions(days).sessions)

    def discover_sessions(self, days: int | None = 7) -> ProviderDiscovery:
        self.discoveries += 1
        return ProviderDiscovery(self.available, (self.session,) if self.available else ())

    def get_session_data(self, session: Session) -> dict[str, Any]:
        self.reads += 1
        return {"messages": [{"role": "user", "content": "work"}]}


@pytest.mark.parametrize("mode", ["list", "search", "interactive", "stats", "collect", "dry-run", "emit-prompt"])
@pytest.mark.parametrize("available", [True, False])
def test_cli_does_not_discover_unselected_providers(mode, available, tmp_path, monkeypatch, capsys) -> None:
    selected = RecordingProvider("codex", tmp_path, available=available)
    excluded = RecordingProvider("kimi", tmp_path)
    scanner = AgentScanner([excluded, selected])
    monkeypatch.setattr("agent_dump.cli.AgentScanner", lambda: scanner)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[ai]\nprovider="openai"\nbase_url="https://example.invalid"\nmodel="test"\napi_key="test"\n'
        "[logging]\nenabled=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_dump.config.get_config_path", lambda: config_path)
    monkeypatch.setattr("agent_dump.cli.request_summary_from_llm", lambda *args, **kwargs: "# report")
    monkeypatch.setattr(
        "agent_dump.cli.request_structured_summary_from_llm", lambda *args, **kwargs: {"requests": ["work"]}
    )
    monkeypatch.setattr("agent_dump.session_workflow.select_sessions_interactive", lambda *args, **kwargs: [])
    if mode in {"collect", "dry-run", "emit-prompt"}:
        args = ["--collect", f"agents://{tmp_path}?providers=codex", "--save", str(tmp_path / "report.md")]
        if mode != "collect":
            args.append(f"--{mode}")
    else:
        args = ["-query", "provider:codex"]
        args.extend(["--search", "work"] if mode == "search" else [f"--{mode}"])
    monkeypatch.setattr("sys.argv", ["agent-dump", *args])

    expected = 1 if mode == "interactive" or (not available and mode in {"collect", "dry-run"}) else 0
    assert main() == expected
    assert selected.discoveries == 1
    assert excluded.discoveries == excluded.reads == 0
    captured = capsys.readouterr()
    assert "Kimi" not in captured.out + captured.err
    if mode == "collect" and available:
        assert (tmp_path / "report.md").read_text(encoding="utf-8") == "# report"


@pytest.mark.parametrize("scope", [None, "codex,kimi"])
def test_cli_keeps_unscoped_and_multiple_provider_discovery(scope, tmp_path, monkeypatch) -> None:
    providers = [RecordingProvider(name, tmp_path) for name in ("codex", "kimi", "pi")]
    monkeypatch.setattr("agent_dump.cli.AgentScanner", lambda: AgentScanner(providers))
    args = ["agent-dump", "--list"]
    if scope:
        args.extend(["-query", f"provider:{scope}"])
    monkeypatch.setattr("sys.argv", args)

    assert main() == 0
    assert [provider.discoveries for provider in providers] == ([1, 1, 1] if scope is None else [1, 1, 0])


@pytest.mark.parametrize("mode", ["list", "search", "stats", "interactive"])
def test_missing_selected_provider_preserves_exit_policy(mode, tmp_path, monkeypatch, capsys) -> None:
    selected = RecordingProvider("codex", tmp_path, available=False)
    excluded = RecordingProvider("kimi", tmp_path)
    monkeypatch.setattr("agent_dump.cli.AgentScanner", lambda: AgentScanner([selected, excluded]))
    args = ["agent-dump", "-query", "provider:codex"]
    args.extend(["--search", "work"] if mode == "search" else [f"--{mode}"])
    monkeypatch.setattr("sys.argv", args)

    assert main() == (1 if mode == "interactive" else 0)
    assert selected.discoveries == 1
    assert excluded.discoveries == 0
    assert expect_contains(capsys.readouterr().out, Keys.DIAG_NO_PROVIDER_IN_SCOPE)
