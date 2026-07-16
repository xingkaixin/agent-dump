"""
测试 CLI 维护模式 workflow
"""

import argparse
from datetime import datetime
from pathlib import Path
from unittest import mock

from agent_dump.agent_registry import AgentRegistration
from agent_dump.agents.base import Session
from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.cli import handle_reindex_mode, handle_stats_mode
from agent_dump.maintenance_workflow import handle_providers_mode as render_provider_capabilities
from agent_dump.paths import SearchRoot


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
        args = argparse.Namespace(days=7, query=None)
        scanner = mock.MagicMock()
        scanner.get_available_agents.return_value = []

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "未找到" in captured.out

    def test_stats_empty_sessions(self, capsys):
        args = argparse.Namespace(days=7, query=None)
        agent = mock.MagicMock()
        agent.display_name = "Claude Code"
        agent.get_sessions.return_value = []

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "未找到会话" in captured.out or "最近 7 天内未找到会话" in captured.out

    def test_stats_shows_counts(self, capsys):
        args = argparse.Namespace(days=7, query=None)
        session1 = make_session("s1", "Session 1", metadata={"message_count": 10})
        session2 = make_session("s2", "Session 2", metadata={"message_count": 20})

        agent = mock.MagicMock()
        agent.display_name = "Claude Code"
        agent.get_sessions.return_value = [session1, session2]

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_stats_mode(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "总会话数: 2" in captured.out
        assert "总消息数: 30" in captured.out
        assert "Claude Code: 2 个会话, 30 条消息" in captured.out

    def test_stats_with_query_filter(self, capsys):
        args = argparse.Namespace(days=7, query="bug")
        session = make_session("s1", "Bug fix", metadata={"message_count": 5})

        agent = mock.MagicMock()
        agent.name = "claudecode"
        agent.display_name = "Claude Code"
        agent.get_sessions.return_value = [session]

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            with mock.patch("agent_dump.maintenance_workflow.apply_query_filter", return_value=[session]):
                result = handle_stats_mode(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "总会话数: 1" in captured.out


class TestReindexMode:
    def test_reindex_no_agents_found(self, capsys):
        args = argparse.Namespace(days=7)
        scanner = mock.MagicMock()
        scanner.get_available_agents.return_value = []

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            result = handle_reindex_mode(args)

        assert result == 1
        assert "未找到" in capsys.readouterr().out

    def test_reindex_rebuilds_available_agents(self, capsys):
        args = argparse.Namespace(days=7)
        session = make_session("s1", "Session 1")
        agent = mock.MagicMock()
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [session]

        scanner = mock.MagicMock()
        scanner.agents = [agent]
        scanner.get_available_agents.return_value = [agent]

        index = mock.MagicMock()
        index.is_available = True
        index.rebuild.return_value = 1

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            with mock.patch("agent_dump.search_index.SearchIndex", return_value=index):
                result = handle_reindex_mode(args)

        assert result == 0
        index.rebuild.assert_called_once_with(agent, [session])
        assert "索引重建完成" in capsys.readouterr().out


class TestProvidersMode:
    def test_providers_marks_each_search_root_status(self, capsys, tmp_path) -> None:
        existing_root = tmp_path / "sessions"
        existing_root.mkdir()
        missing_root = tmp_path / "missing"
        agent = OpenCodeAgent()
        registration = AgentRegistration(
            name="opencode",
            display_name="OpenCode",
            factory=lambda: agent,
            uri_schemes=("opencode",),
            location_line="",
        )

        roots = (
            SearchRoot("existing root", existing_root),
            SearchRoot("missing root", missing_root),
        )
        with mock.patch.object(agent, "get_search_roots", return_value=roots):
            result = render_provider_capabilities(registrations=(registration,))

        assert result == 0
        output = capsys.readouterr().out
        assert "已找到 1/2" in output
        assert f"[已找到] existing root: {existing_root}" in output
        assert f"[未找到] missing root: {missing_root}" in output
