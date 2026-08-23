"""CLI query and search tests."""

from datetime import datetime
from pathlib import Path
from unittest import mock

from cli_test_support import (
    configure_scanner_sessions,
    make_export_result,
    make_session,
)

from agent_dump.cli import (
    main,
)
from agent_dump.query_filter import SearchSessionMatch


class TestMain:
    def test_main_agents_query_uri_conflicts_with_query_option(self, capsys):
        with mock.patch("sys.argv", ["agent-dump", "agents://.?q=bug", "-q", "fatal"]):
            result = main()

        assert result == 1
        assert "agents://" in capsys.readouterr().out

    def test_main_agents_query_uri_auto_enables_list(self, capsys):
        scanner = mock.MagicMock()
        known_agent = mock.MagicMock()
        known_agent.name = "codex"
        scanner.agents = [known_agent]
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = []
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            with mock.patch("sys.argv", ["agent-dump", "agents://.?q=bug&providers=codex"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "路径=" in captured.out
        agent.get_sessions.assert_called_once_with(days=7)

    def test_main_agents_query_uri_uses_filtered_sessions_in_interactive(self):
        scanner = mock.MagicMock()
        known_agent = mock.MagicMock()
        known_agent.name = "codex"
        scanner.agents = [known_agent]
        session = make_session("s1", "Bug fix")
        session.metadata = {"cwd": str(Path.cwd())}
        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [session]
        scanner.get_available_agents.return_value = [agent]
        configure_scanner_sessions(scanner)

        with mock.patch("agent_dump.cli.AgentScanner", return_value=scanner):
            with mock.patch(
                "agent_dump.session_workflow.select_sessions_interactive", return_value=[session]
            ) as mock_select_sessions:
                with mock.patch(
                    "agent_dump.session_workflow.export_sessions_for_formats",
                    return_value=make_export_result(),
                ):
                    with mock.patch("sys.argv", ["agent-dump", "agents://.?providers=codex", "--interactive"]):
                        result = main()

        assert result == 1
        assert mock_select_sessions.call_args.args[0] == [session]

    def test_main_query_without_mode_auto_switches_to_list(self, capsys):
        """测试仅指定 -query 时自动进入 --list 模式"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "opencode"
            mock_scanner.agents = [known_agent]

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            mock_agent.get_sessions.return_value = []

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "-query", "报错"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "匹配「报错」" in captured.out

    def test_main_search_uses_dedicated_result_rendering(self, capsys):
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "codex"
            mock_scanner.agents = [known_agent]

            session = make_session("s1", "Auth Timeout")
            agent = mock.MagicMock()
            agent.name = "codex"
            agent.display_name = "Codex"
            agent.get_formatted_title.return_value = "Auth Timeout (2026-01-01 12:00)"
            agent.get_session_uri.return_value = "codex://s1"
            mock_scanner.get_available_agents.return_value = [agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            match = SearchSessionMatch(
                agent=agent,
                session=session,
                snippet="login failed after **auth timeout**",
                rank=2.5,
            )
            with mock.patch("agent_dump.session_workflow.collect_search_matches", return_value=[match]) as mock_collect:
                with mock.patch("agent_dump.session_workflow.display_sessions_list") as mock_display_sessions:
                    with mock.patch("sys.argv", ["agent-dump", "--search", "auth timeout", "--lang", "zh"]):
                        result = main()

        assert result == 0
        spec = mock_collect.call_args.kwargs["spec"]
        assert spec.keyword == "auth timeout"
        mock_display_sessions.assert_not_called()
        captured = capsys.readouterr()
        assert "搜索最近 7 天内匹配「auth timeout」的会话" in captured.out
        assert "命中片段" in captured.out
        assert "login failed after **auth timeout**" in captured.out
        assert "codex://s1" in captured.out

    def test_main_list_mode_with_query_filters_sessions(self, capsys):
        """测试 --list + -query 会调用过滤逻辑"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "opencode"
            mock_scanner.agents = [known_agent]

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"

            session1 = mock.MagicMock()
            session1.id = "s1"
            session2 = mock.MagicMock()
            session2.id = "s2"
            sessions = [session1, session2]

            mock_agent.get_sessions.return_value = sessions
            mock_agent.get_formatted_title.side_effect = lambda s: f"Session {s.id}"
            mock_agent.get_session_uri.side_effect = lambda s: f"opencode://{s.id}"

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch(
                "agent_dump.cli_shared.select_session_groups",
                return_value=[SearchSessionMatch(mock_agent, session2, "error", 0.0)],
            ) as mock_filter:
                with mock.patch("agent_dump.session_workflow.display_search_results") as mock_display_search:
                    with mock.patch("sys.argv", ["agent-dump", "--list", "-query", "error"]):
                        result = main()

        assert result == 0
        assert mock_filter.call_args.args[0] == [(mock_agent, sessions)]
        assert mock_filter.call_args.args[1].keyword == "error"
        mock_display_search.assert_not_called()
        captured = capsys.readouterr()
        assert "OpenCode (1 个会话)" in captured.out

    def test_main_multiple_agents_interactive_with_query_scope(self, capsys):
        """测试 interactive + query agent 范围只在指定范围内选择"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_opencode = mock.MagicMock()
            known_opencode.name = "opencode"
            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            known_kimi = mock.MagicMock()
            known_kimi.name = "kimi"
            mock_scanner.agents = [known_opencode, known_codex, known_kimi]

            agent1 = mock.MagicMock()
            agent1.name = "opencode"
            agent1.display_name = "OpenCode"
            agent1.get_sessions.return_value = [mock.MagicMock()]

            agent2 = mock.MagicMock()
            agent2.name = "codex"
            agent2.display_name = "Codex"
            agent2_sessions = [mock.MagicMock()]
            agent2.get_sessions.return_value = agent2_sessions

            agent3 = mock.MagicMock()
            agent3.name = "kimi"
            agent3.display_name = "Kimi"
            agent3_sessions = [mock.MagicMock()]
            agent3.get_sessions.return_value = agent3_sessions

            mock_scanner.get_available_agents.return_value = [agent1, agent2, agent3]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            selected_session = mock.MagicMock()
            kimi_session = mock.MagicMock()
            with mock.patch(
                "agent_dump.session_workflow.select_agent_interactive", return_value=agent2
            ) as mock_select_agent:
                with mock.patch(
                    "agent_dump.cli_shared.select_session_groups",
                    return_value=[
                        SearchSessionMatch(agent2, selected_session, "bug", 0.0),
                        SearchSessionMatch(agent3, kimi_session, "bug", 0.0),
                    ],
                ) as mock_filter:
                    with mock.patch(
                        "agent_dump.session_workflow.select_sessions_interactive",
                        return_value=[selected_session],
                    ):
                        with mock.patch(
                            "agent_dump.session_workflow.export_sessions_for_formats",
                            return_value=make_export_result(Path("a.json")),
                        ):
                            with mock.patch(
                                "sys.argv",
                                ["agent-dump", "--interactive", "-query", "codex,kimi:bug"],
                            ):
                                result = main()

        assert result == 0
        scoped_agents = mock_select_agent.call_args[0][0]
        assert [agent.name for agent in scoped_agents] == ["codex", "kimi"]
        assert mock_select_agent.call_args[0][1] == {"codex": 1, "kimi": 1}
        mock_filter.assert_called_once()
        assert mock_filter.call_args.args[0] == [(agent2, agent2_sessions), (agent3, agent3_sessions)]
        captured = capsys.readouterr()
        assert "已选择: Codex" in captured.out

    def test_main_days_and_query_filters_with_and_relation(self):
        """测试 -days 与 -query 同时存在时都会生效"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "opencode"
            mock_scanner.agents = [known_agent]

            mock_agent = mock.MagicMock()
            mock_agent.name = "opencode"
            mock_agent.display_name = "OpenCode"
            sessions = [mock.MagicMock(), mock.MagicMock()]
            mock_agent.get_sessions.return_value = sessions

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            selected_sessions = [mock.MagicMock()]
            with mock.patch(
                "agent_dump.cli_shared.select_session_groups",
                return_value=[SearchSessionMatch(mock_agent, selected_sessions[0], "bug", 0.0)],
            ) as mock_filter:
                with mock.patch(
                    "agent_dump.session_workflow.select_sessions_interactive", return_value=selected_sessions
                ):
                    with mock.patch(
                        "agent_dump.session_workflow.export_sessions_for_formats",
                        return_value=make_export_result(Path("a.json")),
                    ):
                        with mock.patch(
                            "sys.argv",
                            ["agent-dump", "--interactive", "-days", "3", "-query", "bug"],
                        ):
                            result = main()

        assert result == 0
        mock_agent.get_sessions.assert_called_once_with(days=3)
        assert mock_filter.call_args.args[0] == [(mock_agent, sessions)]
        assert mock_filter.call_args.args[1].keyword == "bug"

    def test_main_invalid_query_with_unknown_agent(self, capsys):
        """测试 query 中包含未知 agent 时返回错误"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_opencode = mock.MagicMock()
            known_opencode.name = "opencode"
            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            mock_scanner.agents = [known_opencode, known_codex]
            mock_scanner.get_available_agents.return_value = [known_opencode]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "-query", "codex,unknown:bug"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "查询条件无效" in captured.out
        assert "未知 agent 名称" in captured.out
        assert "下一步" in captured.out

    def test_main_invalid_structured_query_returns_error(self, capsys):
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "codex"
            mock_scanner.agents = [known_agent]
            mock_scanner.get_available_agents.return_value = [known_agent]
            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("sys.argv", ["agent-dump", "-query", "bug provider:codex foo:bar"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "查询条件无效" in captured.out
        assert "下一步" in captured.out

    def test_main_list_mode_with_structured_query_uses_query_filter(self, capsys):
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()
            known_agent = mock.MagicMock()
            known_agent.name = "codex"
            mock_scanner.agents = [known_agent]

            session = mock.MagicMock()
            session.id = "s1"

            mock_agent = mock.MagicMock()
            mock_agent.name = "codex"
            mock_agent.display_name = "Codex"
            mock_agent.get_sessions.return_value = [session]
            mock_agent.get_formatted_title.return_value = "Session s1"
            mock_agent.get_session_uri.return_value = "codex://s1"

            mock_scanner.get_available_agents.return_value = [mock_agent]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch(
                "agent_dump.cli_shared.select_session_groups",
                return_value=[SearchSessionMatch(mock_agent, session, "bug", 0.0, "user")],
            ) as mock_filter:
                with mock.patch("sys.argv", ["agent-dump", "--list", "-query", "bug role:user path:."]):
                    result = main()

        assert result == 0
        spec = mock_filter.call_args.args[1]
        assert spec.keyword == "bug"
        assert spec.roles == {"user"}
        assert spec.project_path == Path.cwd().resolve()
        assert "roles=user" in capsys.readouterr().out

    def test_main_interactive_query_no_match_returns_1(self, capsys):
        """测试 interactive + query 全部无命中时返回 1"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            known_kimi = mock.MagicMock()
            known_kimi.name = "kimi"
            mock_scanner.agents = [known_codex, known_kimi]

            agent_codex = mock.MagicMock()
            agent_codex.name = "codex"
            agent_codex.display_name = "Codex"
            agent_codex.get_sessions.return_value = [mock.MagicMock()]

            agent_kimi = mock.MagicMock()
            agent_kimi.name = "kimi"
            agent_kimi.display_name = "Kimi"
            agent_kimi.get_sessions.return_value = [mock.MagicMock()]

            mock_scanner.get_available_agents.return_value = [agent_codex, agent_kimi]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with mock.patch("agent_dump.cli_shared.select_session_groups", return_value=[]) as mock_filter:
                with mock.patch("agent_dump.session_workflow.select_agent_interactive") as mock_select_agent:
                    with mock.patch("sys.argv", ["agent-dump", "--interactive", "-query", "codex,kimi:bug"]):
                        result = main()

        assert result == 1
        mock_filter.assert_called_once()
        mock_select_agent.assert_not_called()
        captured = capsys.readouterr()
        assert "未找到最近 7 天内匹配「关键词=bug；providers=codex,kimi」的会话" in captured.out

    def test_main_interactive_structured_query_applies_global_limit(self, capsys):
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            known_kimi = mock.MagicMock()
            known_kimi.name = "kimi"
            mock_scanner.agents = [known_codex, known_kimi]

            codex_session = make_session("codex-1", "codex", created_at=datetime(2026, 1, 1, 10, 0, 0))
            kimi_session = make_session("kimi-1", "kimi", created_at=datetime(2026, 1, 1, 11, 0, 0))

            agent_codex = mock.MagicMock()
            agent_codex.name = "codex"
            agent_codex.display_name = "Codex"
            agent_codex.get_sessions.return_value = [codex_session]

            agent_kimi = mock.MagicMock()
            agent_kimi.name = "kimi"
            agent_kimi.display_name = "Kimi"
            agent_kimi.get_sessions.return_value = [kimi_session]

            mock_scanner.get_available_agents.return_value = [agent_codex, agent_kimi]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            with (
                mock.patch(
                    "agent_dump.cli_shared.select_session_groups",
                    return_value=[SearchSessionMatch(agent_kimi, kimi_session, "bug", 0.0)],
                ) as mock_filter,
                mock.patch("agent_dump.session_workflow.select_agent_interactive") as mock_select_agent,
            ):
                with mock.patch("agent_dump.session_workflow.select_sessions_interactive", return_value=[kimi_session]):
                    with mock.patch(
                        "agent_dump.session_workflow.export_sessions_for_formats",
                        return_value=make_export_result(Path("a.json")),
                    ):
                        with mock.patch(
                            "sys.argv",
                            ["agent-dump", "--interactive", "-query", "bug limit:1 provider:codex,kimi"],
                        ):
                            result = main()

        assert result == 0
        mock_filter.assert_called_once()
        mock_select_agent.assert_not_called()
        assert "自动选择: Kimi" in capsys.readouterr().out

    def test_main_interactive_query_auto_selects_only_matched_agent(self, capsys):
        """测试 interactive + query 仅一个 agent 命中时自动选择"""
        with mock.patch("agent_dump.cli.AgentScanner") as mock_scanner_class:
            mock_scanner = mock.MagicMock()

            known_codex = mock.MagicMock()
            known_codex.name = "codex"
            known_kimi = mock.MagicMock()
            known_kimi.name = "kimi"
            mock_scanner.agents = [known_codex, known_kimi]

            agent_codex = mock.MagicMock()
            agent_codex.name = "codex"
            agent_codex.display_name = "Codex"
            codex_sessions = [mock.MagicMock()]
            agent_codex.get_sessions.return_value = codex_sessions

            agent_kimi = mock.MagicMock()
            agent_kimi.name = "kimi"
            agent_kimi.display_name = "Kimi"
            kimi_sessions = [mock.MagicMock()]
            agent_kimi.get_sessions.return_value = kimi_sessions

            mock_scanner.get_available_agents.return_value = [agent_codex, agent_kimi]

            configure_scanner_sessions(mock_scanner)
            mock_scanner_class.return_value = mock_scanner

            selected_session = mock.MagicMock()
            with (
                mock.patch(
                    "agent_dump.cli_shared.select_session_groups",
                    return_value=[SearchSessionMatch(agent_codex, selected_session, "bug", 0.0)],
                ) as mock_filter,
                mock.patch("agent_dump.session_workflow.select_agent_interactive") as mock_select_agent,
                mock.patch(
                    "agent_dump.session_workflow.select_sessions_interactive",
                    return_value=[selected_session],
                ),
                mock.patch(
                    "agent_dump.session_workflow.export_sessions_for_formats",
                    return_value=make_export_result(Path("a.json")),
                ),
            ):
                with mock.patch("sys.argv", ["agent-dump", "--interactive", "-query", "codex,kimi:bug"]):
                    result = main()

        assert result == 0
        mock_filter.assert_called_once()
        assert mock_filter.call_args.args[0] == [(agent_codex, codex_sessions), (agent_kimi, kimi_sessions)]
        mock_select_agent.assert_not_called()
        captured = capsys.readouterr()
        assert "自动选择: Codex" in captured.out
