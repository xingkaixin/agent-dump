"""
测试 agents/base.py 模块
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from unittest import mock

import pytest

from agent_dump.agents.base import BaseAgent, MessageCountCompleteness, MessageCountFact, ProviderDiscovery, Session


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


class TestProviderDiscovery:
    def test_unavailable_result_cannot_contain_sessions(self) -> None:
        session = Session(
            id="test-id",
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source_path=Path("/test"),
            metadata={},
        )

        with pytest.raises(ValueError, match="unavailable provider discovery"):
            ProviderDiscovery(available=False, sessions=(session,))


class TestMessageCountFact:
    @pytest.mark.parametrize("value", [None, True, -1, "12"])
    def test_untrusted_values_are_unknown(self, value):
        fact = MessageCountFact.from_provider_value(value)

        assert fact.value is None
        assert fact.completeness is MessageCountCompleteness.UNKNOWN

    @pytest.mark.parametrize("value", [0, 12])
    def test_non_negative_integers_are_exact(self, value):
        fact = MessageCountFact.from_provider_value(value)

        assert fact.value == value
        assert fact.exact_value == value
        assert fact.completeness is MessageCountCompleteness.EXACT

    def test_unknown_count_cannot_be_read_as_exact(self):
        fact = MessageCountFact.from_provider_value(None)

        with pytest.raises(ValueError, match="not exact"):
            _ = fact.exact_value


class ConcreteAgent(BaseAgent):
    """用于测试的具体 Agent 实现"""

    def __init__(self):
        super().__init__("concrete", "Concrete Agent")
        self._available = True
        self._sessions = []
        self.data_reads = 0
        self.requested_days: list[int | None] = []

    def is_available(self):
        return self._available

    def get_sessions(self, days: int | None = 7):
        self.requested_days.append(days)
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

    def test_scan_requests_all_sessions_from_canonical_reader(self):
        agent = ConcreteAgent()

        assert agent.scan() == []
        assert agent.requested_days == [None]

    def test_available_session_read_skips_reader_when_unavailable(self):
        agent = ConcreteAgent()
        agent._available = False

        assert agent.discover_sessions(3) == ProviderDiscovery(available=False)
        assert agent.requested_days == []

    def test_available_session_read_returns_requested_window(self):
        agent = ConcreteAgent()

        assert agent.discover_sessions(3) == ProviderDiscovery(available=True)
        assert agent.requested_days == [3]

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

        assert first == second
        assert first is not second
        assert agent.data_reads == 1

    def test_cached_session_data_isolates_nested_consumer_mutations(self, tmp_path):
        agent = ConcreteAgent()
        session = Session(
            id="isolated",
            title="Isolated",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=tmp_path / "isolated.jsonl",
            metadata={},
        )

        first = agent.get_cached_session_data(session)
        first["messages"].append({"role": "user", "content": "mutated"})
        second = agent.get_cached_session_data(session)

        assert second["messages"] == []
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

        with mock.patch.object(agent, "get_session_change_sources", return_value=(context_file,)):
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
        assert all(result == results[0] for result in results)
        assert len({id(result) for result in results}) == len(results)

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

        assert result == expected
        assert result is not expected
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
                "model_provider": "gpt-5",
                "message_count": 12,
            },
        )

        with mock.patch("agent_dump.time_utils.get_local_timezone", return_value=timezone.utc):
            result = agent.get_session_summary_fields(session)

        assert result == {
            "cwd_project": "/workspace/demo",
            "model": "gpt-5",
            "message_count": 12,
            "message_count_completeness": "exact",
            "updated_at": "2024-01-01 11:00",
        }
        assert agent.get_session_head(session)["model"] == result["model"]

    def test_get_session_facts_distinguishes_location_project_and_source(self):
        agent = ConcreteAgent()
        source = Path("/provider/projects/project-hash/session.jsonl")
        session = Session(
            id="test",
            title="Test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=source,
            metadata={
                "cwd": "/workspace/real",
                "directory": "/workspace/legacy",
                "project": "project-hash",
                "model": "gpt-5",
            },
        )

        facts = agent.get_session_facts(session)

        assert facts.working_directory == Path("/workspace/real")
        assert facts.provider_project == "project-hash"
        assert facts.model == "gpt-5"
        assert facts.session_source == source
        assert facts.change_sources == ()
        assert facts.message_count.completeness is MessageCountCompleteness.UNKNOWN
        assert facts.display_location == "/workspace/real"
        assert agent.get_session_head(session)["cwd_or_project"] == "/workspace/real"
        assert agent.get_session_summary_fields(session)["cwd_project"] == "/workspace/real"

    def test_get_session_facts_display_falls_back_without_conflating_source(self):
        agent = ConcreteAgent()
        project_session = Session(
            id="project",
            title="Project",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=Path("/provider/project/session.jsonl"),
            metadata={"project": "provider-project"},
        )
        source_session = Session(
            id="source",
            title="Source",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=Path("/provider/source"),
            metadata={},
        )

        project_facts = agent.get_session_facts(project_session)
        source_facts = agent.get_session_facts(source_session)

        assert project_facts.working_directory is None
        assert project_facts.display_location == "provider-project"
        assert source_facts.working_directory is None
        assert source_facts.provider_project is None
        assert source_facts.display_location == "/provider/source"

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
        assert result["message_count_completeness"] == "unknown"
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

        assert result.parent == output_dir
        assert result.name.startswith("~")
        assert result.name.endswith(".raw.jsonl")
        assert result.read_text(encoding="utf-8") == "{}\n"
        assert not (tmp_path / "escaped.raw.jsonl").exists()

    def test_export_session_with_fields_uses_shared_json_writer(self, tmp_path):
        agent = ConcreteAgent()
        session = Session(
            id="session",
            title="Session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source_path=tmp_path / "session.jsonl",
            metadata={},
        )

        result = agent.export_session_with_fields(session, tmp_path / "exports", {"uri": "concrete://session"})

        assert json.loads(result.read_text(encoding="utf-8")) == {
            "id": "session",
            "title": "Session",
            "messages": [],
            "uri": "concrete://session",
        }

    def test_export_session_preserves_legacy_payload_hook(self, tmp_path: Path) -> None:
        agent = ConcreteAgent()
        now = datetime.now(timezone.utc)
        session = Session("session", "Session", now, now, tmp_path / "missing.jsonl", {})

        def legacy_payload(selected: Session) -> dict[str, object]:
            return {"id": selected.id, "custom": "legacy export"}

        with mock.patch.object(agent, "_json_export_payload", side_effect=legacy_payload) as prepare:
            result = BaseAgent.export_session(agent, session, tmp_path / "exports")

        prepare.assert_called_once_with(session)
        assert json.loads(result.read_text(encoding="utf-8")) == {"id": "session", "custom": "legacy export"}
        assert agent.data_reads == 0

    @pytest.mark.parametrize("prepared", [{}, {"messages": [{"parts": [{"text": "prepared"}]}]}])
    def test_export_uses_isolated_prepared_payload_without_loading(self, tmp_path: Path, prepared: dict) -> None:
        agent = ConcreteAgent()
        now = datetime.now(timezone.utc)
        session = Session("session", "Session", now, now, tmp_path / "missing.jsonl", {})
        before = json.loads(json.dumps(prepared))

        result = agent.export_session_with_fields(
            session, tmp_path / "exports", {"summary": "prepared summary"}, session_data=prepared
        )

        assert json.loads(result.read_text(encoding="utf-8")) == {**before, "summary": "prepared summary"}
        payload = agent._json_export_payload(session, session_data=prepared)
        payload.setdefault("messages", []).append({"parts": [{"text": "export only"}]})
        if before:
            payload["messages"][0]["parts"][0]["text"] = "changed for export"
        assert prepared == before
        assert agent.data_reads == 0
