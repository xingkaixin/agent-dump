"""collect 模块测试。"""

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.agents.base import Session
from agent_dump.collect import (
    CollectEntry,
    build_collect_prompt,
    collect_entries,
    request_summary_from_llm,
    resolve_collect_date_range,
    write_collect_markdown,
)
from agent_dump.config import AIConfig


class TestCollectDates:
    def test_both_missing_defaults_today(self):
        today = date(2026, 3, 5)
        since, until = resolve_collect_date_range(None, None, today=today)
        assert since == today
        assert until == today

    def test_since_only_defaults_until_today(self):
        today = date(2026, 3, 5)
        since, until = resolve_collect_date_range("2026-03-01", None, today=today)
        assert since == date(2026, 3, 1)
        assert until == today

    def test_until_only_defaults_since_month_start(self):
        since, until = resolve_collect_date_range(None, "20260210", today=date(2026, 3, 5))
        assert since == date(2026, 2, 1)
        assert until == date(2026, 2, 10)

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            resolve_collect_date_range("2026-03-05", "2026-03-01")


class TestCollectEntries:
    def test_collect_entries_filters_and_renders(self):
        now = datetime.now(timezone.utc)
        in_range = Session(
            id="s-in",
            title="in",
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
            source_path=Path("/tmp/a"),
            metadata={"cwd": "/repo/a"},
        )
        out_range = Session(
            id="s-out",
            title="out",
            created_at=now - timedelta(days=40),
            updated_at=now - timedelta(days=40),
            source_path=Path("/tmp/b"),
            metadata={"cwd": "/repo/b"},
        )

        agent = mock.MagicMock()
        agent.name = "codex"
        agent.display_name = "Codex"
        agent.get_sessions.return_value = [in_range, out_range]
        agent.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        agent.get_session_data.return_value = {"messages": []}

        entries, truncated = collect_entries(
            agents=[agent],
            since_date=(now - timedelta(days=2)).date(),
            until_date=now.date(),
            render_session_text_fn=lambda uri, data: f"# Session Dump\n{uri}\n",
        )

        assert len(entries) == 1
        assert entries[0].session_id == "s-in"
        assert entries[0].project_directory == "/repo/a"
        assert truncated is False

    def test_collect_entries_handles_mixed_naive_aware_datetime(self):
        aware_time = datetime.now(timezone.utc) - timedelta(hours=1)
        naive_time = datetime.now() - timedelta(hours=2)
        session_aware = Session(
            id="aware",
            title="aware",
            created_at=aware_time,
            updated_at=aware_time,
            source_path=Path("/tmp/a"),
            metadata={"cwd": "/repo/a"},
        )
        session_naive = Session(
            id="naive",
            title="naive",
            created_at=naive_time,
            updated_at=naive_time,
            source_path=Path("/tmp/b"),
            metadata={"cwd": "/repo/b"},
        )

        agent1 = mock.MagicMock()
        agent1.name = "codex"
        agent1.display_name = "Codex"
        agent1.get_sessions.return_value = [session_aware]
        agent1.get_session_uri.side_effect = lambda s: f"codex://{s.id}"
        agent1.get_session_data.return_value = {"messages": []}

        agent2 = mock.MagicMock()
        agent2.name = "kimi"
        agent2.display_name = "Kimi"
        agent2.get_sessions.return_value = [session_naive]
        agent2.get_session_uri.side_effect = lambda s: f"kimi://{s.id}"
        agent2.get_session_data.return_value = {"messages": []}

        entries, truncated = collect_entries(
            agents=[agent1, agent2],
            since_date=(datetime.now().date() - timedelta(days=2)),
            until_date=datetime.now().date(),
            render_session_text_fn=lambda uri, data: f"# Session Dump\\n{uri}\\n",
        )

        assert len(entries) == 2
        assert {entry.session_id for entry in entries} == {"aware", "naive"}
        assert truncated is False

    def test_build_collect_prompt_contains_required_sections(self):
        entry = CollectEntry(
            date_value=date(2026, 3, 5),
            created_at=datetime(2026, 3, 5, 10, 0, 0),
            agent_name="codex",
            agent_display_name="Codex",
            session_id="a",
            session_uri="codex://a",
            session_title="task",
            project_directory="/repo",
            text="body",
        )
        prompt = build_collect_prompt(
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            entries=[entry],
            has_truncated=False,
        )

        assert "# 时段工作总结（2026-03-01 ~ 2026-03-05）" in prompt
        assert "## 按日期" in prompt
        assert "## 按项目/目录" in prompt
        assert "## 重点事项（决策/风险/阻塞）" in prompt
        assert "## 产出清单" in prompt
        assert "## 下一步建议" in prompt


class TestCollectLLM:
    def test_request_summary_openai_success(self):
        config = AIConfig(
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key="sk-test",
        )
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "# summary",
                    }
                }
            ]
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = None

        with mock.patch("urllib.request.urlopen", return_value=response):
            result = request_summary_from_llm(config, "prompt")

        assert result == "# summary"

    def test_request_summary_api_error(self):
        config = AIConfig(
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-7-sonnet",
            api_key="ak-test",
        )
        with mock.patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                request_summary_from_llm(config, "prompt")


class TestCollectOutput:
    def test_write_collect_markdown(self, tmp_path):
        path = write_collect_markdown("# report", output_dir=tmp_path, today=date(2026, 3, 5))
        assert path == tmp_path / "agent-dump-collect-20260305.md"
        assert path.read_text(encoding="utf-8") == "# report"
