"""
测试 scanner.py 模块
"""

from datetime import datetime, timezone
from pathlib import Path
import threading
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.scanner import AgentScanner, sessions_per_agent


class TestAgentScanner:
    """测试 AgentScanner 类"""

    def test_init(self):
        """测试初始化时创建所有 agent"""
        scanner = AgentScanner()
        assert len(scanner.agents) == 7
        agent_names = [a.name for a in scanner.agents]
        assert "opencode" in agent_names
        assert "zcode" in agent_names
        assert "codex" in agent_names
        assert "kimi" in agent_names
        assert "claudecode" in agent_names
        assert "cursor" in agent_names
        assert "pi" in agent_names

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
        for agent in scanner.agents[4:]:
            agent.is_available = mock.MagicMock(return_value=False)  # type: ignore

        available = scanner.get_available_agents()

        assert len(available) == 2
        assert available[0] == scanner.agents[0]
        assert available[1] == scanner.agents[2]

    @pytest.mark.parametrize(
        ("failure_stage", "expected_error"),
        [
            ("availability", "PermissionError: permission denied"),
            ("scan", "RuntimeError: database is corrupt"),
        ],
    )
    def test_scan_isolates_provider_failures(
        self,
        failure_stage: str,
        expected_error: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        scanner = AgentScanner()
        broken_agent = scanner.agents[0]
        healthy_agent = scanner.agents[1]
        broken_agent.display_name = "Broken Provider"
        healthy_agent.name = "healthy"
        healthy_session = mock.MagicMock()

        if failure_stage == "availability":
            broken_agent.is_available = mock.MagicMock(side_effect=PermissionError("permission denied"))  # type: ignore
        else:
            broken_agent.is_available = mock.MagicMock(return_value=True)  # type: ignore
            broken_agent.scan = mock.MagicMock(side_effect=RuntimeError("database is corrupt"))  # type: ignore

        healthy_agent.is_available = mock.MagicMock(return_value=True)  # type: ignore
        healthy_agent.scan = mock.MagicMock(return_value=[healthy_session])  # type: ignore
        for agent in scanner.agents[2:]:
            agent.is_available = mock.MagicMock(return_value=False)  # type: ignore

        result = scanner.scan()

        assert result == {"healthy": [healthy_session]}
        warning = capsys.readouterr().err
        assert warning.count("Broken Provider") == 1
        assert expected_error in warning

    def test_get_available_agents_isolates_provider_failures(self, capsys: pytest.CaptureFixture[str]) -> None:
        scanner = AgentScanner()
        broken_agent = scanner.agents[0]
        healthy_agent = scanner.agents[1]
        broken_agent.display_name = "Broken Provider"
        broken_agent.is_available = mock.MagicMock(side_effect=OSError("unreadable directory"))  # type: ignore
        healthy_agent.is_available = mock.MagicMock(return_value=True)  # type: ignore
        for agent in scanner.agents[2:]:
            agent.is_available = mock.MagicMock(return_value=False)  # type: ignore

        available = scanner.get_available_agents()

        assert available == [healthy_agent]
        warning = capsys.readouterr().err
        assert warning.count("Broken Provider") == 1
        assert "OSError: unreadable directory" in warning

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
        """并发性用结构性断言，而不是墙钟阈值。

        原实现让 7 个 agent 各 time.sleep(0.1) 后断言 elapsed < 0.35。在共享的 CI
        runner 上乘以 5 条 Python matrix 是典型的间歇性红灯，还固定付 0.1s 真实睡眠。
        改用 Barrier：要求 7 个 scan 都到达同一屏障后才有任何一个返回——串行执行
        永远无法满足这个条件，所以它比时间比较更强，且不依赖机器负载。
        """
        scanner = AgentScanner()
        agent_count = len(scanner.agents)
        # timeout 只是防止实现真的串行时把测试挂死，不参与正确性判断
        barrier = threading.Barrier(agent_count, timeout=10)
        arrivals: list[str] = []
        lock = threading.Lock()

        def make_scan(agent_name: str):
            def _scan():
                with lock:
                    arrivals.append(agent_name)
                barrier.wait()
                return [mock.MagicMock()]

            return _scan

        for agent in scanner.agents:
            agent.is_available = mock.MagicMock(return_value=True)  # type: ignore
            agent.scan = make_scan(agent.name)

        result = scanner.scan()

        assert len(result) == agent_count
        assert sorted(arrivals) == sorted(agent.name for agent in scanner.agents)

    def test_scan_isolates_a_provider_that_raises(self):
        """并发路径下单个 provider 抛异常仍只影响它自己。"""
        scanner = AgentScanner()
        for index, agent in enumerate(scanner.agents):
            agent.is_available = mock.MagicMock(return_value=True)  # type: ignore
            if index == 0:
                agent.scan = mock.MagicMock(side_effect=ValueError("bad row"))  # type: ignore
            else:
                agent.scan = mock.MagicMock(return_value=[mock.MagicMock()])  # type: ignore

        result = scanner.scan()

        assert len(result) == len(scanner.agents) - 1
        assert scanner.agents[0].name not in result


class ExplodingAgent(BaseAgent):
    """get_sessions 抛异常，模拟一个 provider 的存储里有坏数据。"""

    def __init__(self, name: str = "broken"):
        super().__init__(name=name, display_name=f"Broken-{name}")

    def scan(self) -> list[Session]:
        return []

    def is_available(self) -> bool:
        return True

    def get_sessions(self, days: int = 7) -> list[Session]:
        raise ValueError("malformed row in provider store")

    def export_session(self, session: Session, output_dir: Path) -> Path:
        raise NotImplementedError

    def get_session_data(self, session: Session) -> dict:
        return {}


class HealthyAgent(ExplodingAgent):
    def __init__(self, name: str = "healthy", count: int = 2):
        super().__init__(name=name)
        self._count = count

    def get_sessions(self, days: int = 7) -> list[Session]:
        return [
            Session(
                id=f"{self.name}-{i}",
                title=f"session {i}",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                source_path=Path("/tmp/x.jsonl"),
                metadata={},
            )
            for i in range(self._count)
        ]


class TestSessionsPerAgent:
    """AD-122：一个 provider 失败不得带走其余 provider。"""

    def test_one_failing_provider_does_not_hide_the_others(self, capsys):
        agents = [HealthyAgent("a", 2), ExplodingAgent("b"), HealthyAgent("c", 3)]

        results = sessions_per_agent(agents, days=7)
        captured = capsys.readouterr()

        assert [(agent.name, len(sessions)) for agent, sessions in results] == [("a", 2), ("b", 0), ("c", 3)]
        assert "Broken-b" in captured.err
        assert "ValueError" in captured.err

    def test_preserves_input_order(self):
        agents = [HealthyAgent(name, 1) for name in ("z", "m", "a")]

        assert [agent.name for agent, _ in sessions_per_agent(agents, days=7)] == ["z", "m", "a"]

    def test_empty_agent_list_is_handled(self):
        assert sessions_per_agent([], days=7) == []

    def test_a_provider_returning_no_sessions_is_not_treated_as_failure(self, capsys):
        results = sessions_per_agent([HealthyAgent("empty", 0)], days=7)
        captured = capsys.readouterr()

        assert results == [(results[0][0], [])]
        assert "警告" not in captured.err, "空结果与失败必须区分开"
