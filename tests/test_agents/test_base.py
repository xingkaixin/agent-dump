"""
测试 agents/base.py 模块
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
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
        self.data_reads = 0

    def scan(self):
        return self._sessions

    def is_available(self):
        return self._available

    def get_sessions(self, days=7):
        return self._sessions

    def export_session(self, session, output_dir):
        return output_dir / f"{session.id}.json"

    def get_session_data(self, session):
        self.data_reads += 1
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

    def test_cached_session_data_reads_once_for_unchanged_session(self, tmp_path):
        agent = ConcreteAgent()
        session = Session(
            id="cached",
            title="Cached",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=tmp_path / "cached.jsonl",
            metadata={},
        )

        first = agent.get_cached_session_data(session)
        second = agent.get_cached_session_data(session)

        assert first is second
        assert agent.data_reads == 1

    def test_cached_session_data_reloads_when_related_file_mtime_changes(self, tmp_path):
        context_file = tmp_path / "context.jsonl"
        context_file.write_text("first", encoding="utf-8")
        agent = ConcreteAgent()
        session = Session(
            id="changed",
            title="Changed",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=tmp_path / "session",
            metadata={"context_file": str(context_file)},
        )

        first = agent.get_cached_session_data(session)
        initial_mtime = context_file.stat().st_mtime
        os.utime(context_file, (initial_mtime + 1, initial_mtime + 1))
        second = agent.get_cached_session_data(session)

        assert first is not second
        assert agent.data_reads == 2

    def test_cached_session_data_coalesces_concurrent_reads(self, tmp_path):
        agent = ConcreteAgent()
        session = Session(
            id="concurrent",
            title="Concurrent",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=tmp_path / "concurrent.jsonl",
            metadata={},
        )
        started = threading.Event()
        release = threading.Event()

        def load_session_data(_session: Session) -> dict[str, object]:
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("cached read was not released")
            return {"messages": []}

        with mock.patch.object(agent, "get_session_data", side_effect=load_session_data) as load:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(agent.get_cached_session_data, session) for _ in range(4)]
                assert started.wait(timeout=5)
                release.set()
                results = [future.result() for future in futures]

        assert load.call_count == 1
        assert all(result is results[0] for result in results)

    def test_cached_session_data_retries_after_failed_read(self, tmp_path):
        agent = ConcreteAgent()
        session = Session(
            id="retry",
            title="Retry",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=tmp_path / "retry.jsonl",
            metadata={},
        )
        expected = {"messages": []}

        with mock.patch.object(
            agent,
            "get_session_data",
            side_effect=[ValueError("temporary failure"), expected],
        ) as load:
            with pytest.raises(ValueError, match="temporary failure"):
                agent.get_cached_session_data(session)
            result = agent.get_cached_session_data(session)

        assert result is expected
        assert load.call_count == 2

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

    def test_find_session_by_id_default_scans_sessions(self):
        """测试默认 find_session_by_id 全量扫描并按 id 匹配"""
        agent = ConcreteAgent()
        target = Session(
            id="target",
            title="Target",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=Path("/test"),
            metadata={},
        )
        other = Session(
            id="other",
            title="Other",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=Path("/test"),
            metadata={},
        )
        agent._sessions = [other, target]

        assert agent.find_session_by_id("target") is target
        assert agent.find_session_by_id("missing") is None

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

    def test_export_raw_session_keeps_untrusted_id_inside_output_dir(self, tmp_path):
        agent = ConcreteAgent()
        source_path = tmp_path / "source.jsonl"
        source_path.write_text("{}\n", encoding="utf-8")
        output_dir = tmp_path / "exports"
        session = Session(
            id=str(tmp_path / "escaped"),
            title="Unsafe id",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=source_path,
            metadata={},
        )

        result = agent.export_raw_session(session, output_dir)

        assert result == output_dir / "escaped.raw.jsonl"
        assert result.read_text(encoding="utf-8") == "{}\n"
        assert not (tmp_path / "escaped.raw.jsonl").exists()
