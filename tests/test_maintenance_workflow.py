"""
测试 CLI 维护模式 workflow
"""

from datetime import datetime
from pathlib import Path
from unittest import mock

from locale_helpers import ALL_LANGUAGES, Keys, expect_contains
import pytest

from agent_dump.agent_registry import AgentRegistration
from agent_dump.agents.base import Session, derive_session_facts
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.cli import handle_reindex_mode, handle_stats_mode
from agent_dump.command_plan import ReindexOperation, StatsOperation
from agent_dump.diagnostics import print_recoverable_diagnostic
from agent_dump.maintenance_workflow import handle_providers_mode as render_provider_capabilities
from agent_dump.paths import SearchRoot
from agent_dump.query_filter import QuerySpec
from agent_dump.text_safety import has_unsafe_body_characters


def configure_scanner_sessions(scanner: mock.MagicMock) -> None:
    for agent in scanner.get_available_agents.return_value:
        agent.get_session_facts.side_effect = derive_session_facts

    def read_sessions(days=7, *, agents=None):
        return [
            (agent, agent.get_sessions(days=days))
            for agent in (agents if agents is not None else scanner.get_available_agents.return_value)
        ]

    scanner.get_sessions.side_effect = read_sessions
    scanner.get_available_sessions.side_effect = read_sessions


def make_session(
    session_id: str,
    title: str,
    *,
    created_at: datetime | None = None,
    source_path: Path | None = None,
    metadata: dict | None = None,
) -> Session:
    session_time = created_at or datetime(2026, 1, 1, 12, 0, 0)
    return Session(
        id=session_id,
        title=title,
        created_at=session_time,
        updated_at=session_time,
        source_path=source_path or Path(f"/tmp/{session_id}.jsonl"),
        metadata=metadata or {},
    )


class TestStatsMode:
    """测试 stats 命令"""

    def test_stats_no_agents_found(self, capsys):
        operation = StatsOperation(days=7, query_spec=None)
        scanner = mock.MagicMock()
        scanner.get_available_agents.return_value = []
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        assert result == 1
        captured = capsys.readouterr()
        assert "未找到" in captured.out

    def test_stats_empty_sessions(self, capsys):
        operation = StatsOperation(days=7, query_spec=None)
        agent = mock.MagicMock()
        agent.display_name = "Claude Code"
        agent.get_sessions.return_value = []

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        assert result == 0
        captured = capsys.readouterr()
        assert "未找到会话" in captured.out or "最近 7 天内未找到会话" in captured.out

    def test_stats_missing_provider_scope_is_not_an_error(self, capsys):
        operation = StatsOperation(
            days=7,
            query_spec=QuerySpec(frozenset({"kimi"}), "bug", None, None, None),
        )
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [make_session("s1", "Bug")]
        agent.get_search_roots.return_value = ()
        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        assert result == 0
        assert expect_contains(capsys.readouterr().out, Keys.DIAG_NO_PROVIDER_IN_SCOPE)

    def test_stats_shows_counts(self, capsys):
        operation = StatsOperation(days=7, query_spec=None)
        session1 = make_session("s1", "Session 1", metadata={"message_count": 10})
        session2 = make_session("s2", "Session 2", metadata={"message_count": 20})

        agent = mock.MagicMock()
        agent.display_name = "Claude Code"
        agent.get_sessions.return_value = [session1, session2]

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        assert result == 0
        captured = capsys.readouterr()
        assert "总会话数: 2" in captured.out
        assert "总消息数: 30" in captured.out
        assert "Claude Code: 2 个会话, 30 条消息" in captured.out

    def test_stats_preserves_an_exact_zero(self, capsys):
        operation = StatsOperation(days=7, query_spec=None)
        session = make_session("s1", "Empty", metadata={"message_count": 0})
        agent = mock.MagicMock(display_name="Codex")
        agent.get_sessions.return_value = [session]
        scanner = mock.MagicMock()
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        output = capsys.readouterr().out
        assert result == 0
        assert expect_contains(output, Keys.STATS_TOTAL_MESSAGES, count=0)
        assert expect_contains(output, Keys.STATS_AGENT_ROW, name="Codex", sessions=1, messages=0)

    @pytest.mark.parametrize("language", ALL_LANGUAGES)
    def test_stats_marks_a_mixed_total_as_incomplete(self, language, use_language, capsys):
        use_language(language)
        operation = StatsOperation(days=7, query_spec=None)
        sessions = [
            make_session("known", "Known", metadata={"message_count": 7}),
            make_session("unknown", "Unknown"),
        ]
        agent = mock.MagicMock(display_name="Codex")
        agent.get_sessions.return_value = sessions
        scanner = mock.MagicMock()
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        output = capsys.readouterr().out
        assert result == 0
        assert expect_contains(output, Keys.STATS_KNOWN_MESSAGES, count=7, unknown_sessions=1)
        assert expect_contains(
            output,
            Keys.STATS_AGENT_ROW_WITH_UNKNOWN,
            name="Codex",
            sessions=2,
            messages=7,
            unknown_sessions=1,
        )
        assert not expect_contains(output, Keys.STATS_TOTAL_MESSAGES, count=7)

    def test_stats_distinguishes_all_unknown_from_exact_zero(self, capsys):
        operation = StatsOperation(days=7, query_spec=None)
        sessions = [make_session("s1", "Unknown 1"), make_session("s2", "Unknown 2")]
        agent = mock.MagicMock(display_name="Codex")
        agent.get_sessions.return_value = sessions
        scanner = mock.MagicMock()
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        output = capsys.readouterr().out
        assert result == 0
        assert expect_contains(output, Keys.STATS_KNOWN_MESSAGES, count=0, unknown_sessions=2)
        assert not expect_contains(output, Keys.STATS_TOTAL_MESSAGES, count=0)

    def test_stats_sanitizes_provider_display_name(self, capsys):
        poison = "Provider\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        operation = StatsOperation(days=7, query_spec=None)
        session = make_session("s1", "Session", metadata={"message_count": 1})
        agent = mock.MagicMock()
        agent.display_name = poison
        agent.get_sessions.return_value = [session]
        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        output = capsys.readouterr().out
        assert result == 0
        assert not has_unsafe_body_characters(output)
        assert "FORGED" in output

    def test_stats_with_query_filter(self, capsys):
        operation = StatsOperation(days=7, query_spec=QuerySpec(None, "bug", None, None, None))
        session = make_session("s1", "Bug fix", metadata={"message_count": 5})

        agent = mock.MagicMock()
        agent.name = "claudecode"
        agent.display_name = "Claude Code"
        agent.get_sessions.return_value = [session]

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            with mock.patch(
                "agent_dump.maintenance_workflow.collect_query_matches",
                return_value={agent.name: [session]},
            ):
                result = handle_stats_mode(operation)

        assert result == 0
        captured = capsys.readouterr()
        assert "总会话数: 1" in captured.out

    def test_stats_applies_query_limit_globally_across_agents(self, capsys):
        operation = StatsOperation(days=7, query_spec=QuerySpec(None, None, None, None, 1))
        older = make_session(
            "older",
            "Older",
            created_at=datetime(2026, 1, 1, 12, 0, 0),
            metadata={"message_count": 3},
        )
        newer = make_session(
            "newer",
            "Newer",
            created_at=datetime(2026, 1, 2, 12, 0, 0),
            metadata={"message_count": 5},
        )
        first_agent = mock.MagicMock(name="first_agent")
        first_agent.name = "codex"
        first_agent.display_name = "Codex"
        first_agent.get_sessions.return_value = [older]
        second_agent = mock.MagicMock(name="second_agent")
        second_agent.name = "kimi"
        second_agent.display_name = "Kimi"
        second_agent.get_sessions.return_value = [newer]

        scanner = mock.MagicMock()
        scanner.agents = [first_agent, second_agent]
        scanner.get_available_agents.return_value = [first_agent, second_agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(operation)

        output = capsys.readouterr().out
        assert result == 0
        assert expect_contains(output, Keys.STATS_TOTAL_SESSIONS, count=1)
        assert expect_contains(output, Keys.STATS_TOTAL_MESSAGES, count=5)


class TestReindexMode:
    def test_reindex_no_agents_found(self, capsys):
        operation = ReindexOperation(days=7)
        scanner = mock.MagicMock()
        scanner.get_available_agents.return_value = []
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_reindex_mode(operation)

        assert result == 1
        assert "未找到" in capsys.readouterr().out

    def test_reindex_rebuilds_available_agents(self, capsys):
        operation = ReindexOperation(days=7)
        session = make_session("s1", "Session 1")
        agent = mock.MagicMock()
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [session]

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        index = mock.MagicMock()
        index.is_available = True
        index.rebuild.return_value = 1

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            with mock.patch("agent_dump.search_index.SearchIndex", return_value=index):
                result = handle_reindex_mode(operation)

        assert result == 0
        index.rebuild.assert_called_once_with(agent, [session], diagnostic_sink=print_recoverable_diagnostic)
        assert "索引重建完成" in capsys.readouterr().out


class TestProvidersMode:
    def test_providers_marks_each_search_root_status(self, capsys, tmp_path) -> None:
        existing_root = tmp_path / "sessions"
        existing_root.mkdir()
        missing_root = tmp_path / "missing"
        registration = AgentRegistration(
            factory=OpenCodeAgent,
            uri_schemes=("opencode",),
        )

        roots = (
            SearchRoot("existing root", existing_root),
            SearchRoot("missing root", missing_root),
        )
        with mock.patch.object(OpenCodeAgent, "get_search_roots", return_value=roots):
            result = render_provider_capabilities(registrations=(registration,))

        assert result == 0
        output = capsys.readouterr().out
        provider_row = next(line for line in output.splitlines() if line.startswith("OpenCode |"))
        assert provider_row.split(" | ")[3] == "已找到 1/2"
        assert "已找到 1/2" in output
        assert f"[已找到] existing root: {existing_root}" in output
        assert f"[未找到] missing root: {missing_root}" in output

    def test_providers_sanitizes_registration_and_search_root_fields(self, capsys, tmp_path) -> None:
        poison = "Provider\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"

        class PoisonAgent(OpenCodeAgent):
            provider_display_name = poison

        registration = AgentRegistration(
            factory=PoisonAgent,
            uri_schemes=(poison,),
        )
        roots = (SearchRoot(poison, tmp_path / poison),)

        with mock.patch.object(PoisonAgent, "get_search_roots", return_value=roots):
            result = render_provider_capabilities(registrations=(registration,))

        output = capsys.readouterr().out
        assert result == 0
        assert not has_unsafe_body_characters(output)
        assert "FORGED" in output
