"""
测试 agents/base.py 模块
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, Session


class TestSession:
    """测试 Session 数据类"""

    def test_session_creation(self):
        """测试创建 Session 对象"""
        session = Session(
            id="test-id",
            title="Test Title",
            created_at=datetime(2024, 1, 1, 10, 0, 0),
            updated_at=datetime(2024, 1, 1, 11, 0, 0),
            source_path=Path("/test/path"),
            metadata={"key": "value"},
        )

        assert session.id == "test-id"
        assert session.title == "Test Title"
        assert session.created_at == datetime(2024, 1, 1, 10, 0, 0)
        assert session.updated_at == datetime(2024, 1, 1, 11, 0, 0)
        assert session.source_path == Path("/test/path")
        assert session.metadata == {"key": "value"}

    def test_session_empty_metadata(self):
        """测试创建带有空 metadata 的 Session"""
        session = Session(
            id="test-id",
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=Path("/test"),
            metadata={},
        )

        assert session.metadata == {}


class ConcreteAgent(BaseAgent):
    """用于测试的具体 Agent 实现"""

    def __init__(self):
        super().__init__("concrete", "Concrete Agent")
        self._available = True
        self._sessions = []

    def scan(self):
        return self._sessions

    def is_available(self):
        return self._available

    def get_sessions(self, days=7):
        return self._sessions

    def export_session(self, session, output_dir):
        return output_dir / f"{session.id}.json"

    def get_session_data(self, session):
        return {
            "id": session.id,
            "title": session.title,
            "messages": [],
        }


class TestBaseAgent:
    """测试 BaseAgent 抽象基类"""

    def test_init(self):
        """测试基类初始化"""
        agent = ConcreteAgent()
        assert agent.name == "concrete"
        assert agent.display_name == "Concrete Agent"

    def test_get_formatted_title_short(self):
        """测试短标题格式化"""
        agent = ConcreteAgent()
        session = Session(
            id="test",
            title="Short Title",
            created_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            updated_at=datetime.now(),
            source_path=Path("/test"),
            metadata={},
        )

        with mock.patch("agent_dump.time_utils.get_local_timezone", return_value=timezone.utc):
            result = agent.get_formatted_title(session)

        assert result == "Short Title (2024-01-01 10:30)"

    def test_get_formatted_title_long(self):
        """测试长标题截断"""
        agent = ConcreteAgent()
        session = Session(
            id="test",
            title="A" * 100,
            created_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            updated_at=datetime.now(),
            source_path=Path("/test"),
            metadata={},
        )

        with mock.patch("agent_dump.time_utils.get_local_timezone", return_value=timezone.utc):
            result = agent.get_formatted_title(session)

        assert "..." in result
        assert "(2024-01-01 10:30)" in result
        assert len(result.split("...")[0]) <= 60

    def test_get_formatted_title_exact_60(self):
        """测试恰好 60 个字符的标题"""
        agent = ConcreteAgent()
        session = Session(
            id="test",
            title="A" * 60,
            created_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            updated_at=datetime.now(),
            source_path=Path("/test"),
            metadata={},
        )

        with mock.patch("agent_dump.time_utils.get_local_timezone", return_value=timezone.utc):
            result = agent.get_formatted_title(session)

        # 60 字符不应截断
        assert "..." not in result
        assert "(2024-01-01 10:30)" in result

    def test_get_formatted_title_61_chars(self):
        """测试 61 个字符的标题（应截断）"""
        agent = ConcreteAgent()
        session = Session(
            id="test",
            title="A" * 61,
            created_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            updated_at=datetime.now(),
            source_path=Path("/test"),
            metadata={},
        )

        with mock.patch("agent_dump.time_utils.get_local_timezone", return_value=timezone.utc):
            result = agent.get_formatted_title(session)

        # 61 字符应截断
        assert "..." in result

    def test_abstract_methods(self):
        """测试抽象方法必须实现"""

        class IncompleteAgent(BaseAgent):
            def __init__(self):
                super().__init__("incomplete", "Incomplete")

        with pytest.raises(TypeError) as exc_info:
            IncompleteAgent()

        assert "abstract" in str(exc_info.value).lower()

    def test_concrete_agent_isinstance(self):
        """测试具体实现是 BaseAgent 的实例"""
        agent = ConcreteAgent()
        assert isinstance(agent, BaseAgent)

    def test_get_session_summary_fields(self):
        """测试默认摘要字段提取"""
        agent = ConcreteAgent()
        session = Session(
            id="test",
            title="Test",
            created_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            source_path=Path("/test"),
            metadata={
                "cwd": "/workspace/demo",
                "model": "gpt-5",
                "message_count": 12,
            },
        )

        with mock.patch("agent_dump.time_utils.get_local_timezone", return_value=timezone.utc):
            result = agent.get_session_summary_fields(session)

        assert result == {
            "cwd_project": "/workspace/demo",
            "model": "gpt-5",
            "branch": None,
            "message_count": 12,
            "updated_at": "2024-01-01 11:00",
        }

    def test_get_session_head_uses_default_fields(self):
        """测试默认 head 信息来自 Session 公共字段。"""
        agent = ConcreteAgent()
        session = Session(
            id="test",
            title="Head Title",
            created_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 11, 30, 0, tzinfo=timezone.utc),
            source_path=Path("/workspace/session.jsonl"),
            metadata={"cwd": "/workspace/project", "model": "gpt-5"},
        )

        result = agent.get_session_head(session)

        assert result["uri"] == "concrete://test"
        assert result["agent"] == "Concrete Agent"
        assert result["title"] == "Head Title"
        assert result["cwd_or_project"] == "/workspace/project"
        assert result["model"] == "gpt-5"
        assert result["message_count"] is None
        assert result["subtargets"] == []
