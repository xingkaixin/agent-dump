"""
测试 scanner.py 模块
"""

from unittest import mock

import pytest

from agent_dump.scanner import AgentScanner


class TestAgentScanner:
    """测试 AgentScanner 类"""

    def test_init(self):
        """测试初始化时创建所有 agent"""
        scanner = AgentScanner()
        assert len(scanner.agents) == 5
        agent_names = [a.name for a in scanner.agents]
        assert "opencode" in agent_names
        assert "codex" in agent_names
        assert "kimi" in agent_names
        assert "claudecode" in agent_names
        assert "cursor" in agent_names

    def test_scan_no_available_agents(self, capsys):
        """测试没有可用 agent 时的扫描"""
        scanner = AgentScanner()

        # Mock 所有 agent 都不可用
        for agent in scanner.agents:
            agent.is_available = mock.MagicMock(return_value=False)  # type: ignore
            agent.scan = mock.MagicMock(return_value=[])  # type: ignore

        result = scanner.scan()

        assert result == {}
        captured = capsys.readouterr()
        assert "正在扫描" in captured.out

    def test_scan_with_available_agents(self, capsys):
        """测试有可用的 agent 时的扫描"""
        scanner = AgentScanner()

        # 创建 mock sessions
        mock_session = mock.MagicMock()
        mock_session.id = "test-session"

        # Mock 第一个 agent 可用且有会话
        scanner.agents[0].is_available = mock.MagicMock(return_value=True)  # type: ignore
        scanner.agents[0].scan = mock.MagicMock(return_value=[mock_session])  # type: ignore
        scanner.agents[0].name = "opencode"
        scanner.agents[0].display_name = "OpenCode"

        # Mock 其他 agent 不可用
        for agent in scanner.agents[1:]:
            agent.is_available = mock.MagicMock(return_value=False)  # type: ignore
            agent.scan = mock.MagicMock(return_value=[])  # type: ignore

        result = scanner.scan()

        assert "opencode" in result
        assert len(result["opencode"]) == 1
        captured = capsys.readouterr()
        assert "OpenCode" in captured.out
        assert "1 个会话" in captured.out

    def test_scan_with_empty_sessions(self, capsys):
        """测试 agent 可用但无会话时的扫描"""
        scanner = AgentScanner()

        # Mock 第一个 agent 可用但无会话
        scanner.agents[0].is_available = mock.MagicMock(return_value=True)  # type: ignore
        scanner.agents[0].scan = mock.MagicMock(return_value=[])  # type: ignore
        scanner.agents[0].name = "opencode"
        scanner.agents[0].display_name = "OpenCode"

        # Mock 其他 agent 不可用
        for agent in scanner.agents[1:]:
            agent.is_available = mock.MagicMock(return_value=False)  # type: ignore
            agent.scan = mock.MagicMock(return_value=[])  # type: ignore

        result = scanner.scan()

        assert result == {}
        captured = capsys.readouterr()
        assert "0 个会话" in captured.out

    def test_get_available_agents(self):
        """测试获取可用 agent 列表"""
        scanner = AgentScanner()

        # Mock 部分 agent 可用
        scanner.agents[0].is_available = mock.MagicMock(return_value=True)  # type: ignore
        scanner.agents[1].is_available = mock.MagicMock(return_value=False)  # type: ignore
        scanner.agents[2].is_available = mock.MagicMock(return_value=True)  # type: ignore
        scanner.agents[3].is_available = mock.MagicMock(return_value=False)  # type: ignore
        scanner.agents[4].is_available = mock.MagicMock(return_value=False)  # type: ignore

        available = scanner.get_available_agents()

        assert len(available) == 2
        assert available[0] == scanner.agents[0]
        assert available[1] == scanner.agents[2]

    def test_get_agent_by_name_found(self):
        """测试通过名称获取存在的 agent"""
        scanner = AgentScanner()

        # Mock opencode 可用
        scanner.agents[0].is_available = mock.MagicMock(return_value=True)  # type: ignore

        agent = scanner.get_agent_by_name("opencode")

        assert agent is not None
        assert agent.name == "opencode"

    def test_get_agent_by_name_not_found(self):
        """测试通过名称获取不存在的 agent"""
        scanner = AgentScanner()

        agent = scanner.get_agent_by_name("nonexistent")

        assert agent is None

    def test_get_agent_by_name_not_available(self):
        """测试 agent 存在但不可用"""
        scanner = AgentScanner()

        # Mock opencode 不可用
        scanner.agents[0].is_available = mock.MagicMock(return_value=False)  # type: ignore

        agent = scanner.get_agent_by_name("opencode")

        assert agent is None

    def test_scan_with_multiple_agents(self, capsys):
        """测试多个 agent 同时可用的情况"""
        scanner = AgentScanner()

        # Mock 所有 agent 都可用
        for i, agent in enumerate(scanner.agents):
            agent.is_available = mock.MagicMock(return_value=True)  # type: ignore
            agent.scan = mock.MagicMock(return_value=[mock.MagicMock()] * (i + 1))  # type: ignore

        result = scanner.scan()

        assert len(result) == len(scanner.agents)
        captured = capsys.readouterr()
        for agent in scanner.agents:
            assert agent.display_name in captured.out

    def test_scan_runs_concurrently(self):
        """测试并发扫描确实并行执行，总时间接近最慢单个 agent 的时间"""
        import time

        scanner = AgentScanner()

        def make_delayed_scan(delay: float):
            def _scan():
                time.sleep(delay)
                return [mock.MagicMock()]
            return _scan

        for agent in scanner.agents:
            agent.is_available = mock.MagicMock(return_value=True)  # type: ignore
            agent.scan = make_delayed_scan(0.1)  # type: ignore

        start = time.monotonic()
        result = scanner.scan()
        elapsed = time.monotonic() - start

        assert len(result) == len(scanner.agents)
        # 5 个 agent 各 0.1s，若串行需 0.5s；并发应远小于 0.5s
        assert elapsed < 0.35
