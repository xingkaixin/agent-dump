from unittest import mock

import pytest

from agent_dump.config import AIConfig
from agent_dump.uri_workflow import build_uri_summary_prompt, maybe_generate_uri_summary


def test_build_uri_summary_prompt_includes_source_and_constraints() -> None:
    prompt = build_uri_summary_prompt("codex://session-001", "# Session Dump\n\n## 1. User\n\nHello")

    assert (
        prompt
        == """你是一个严谨的会话总结助手。
请基于下面的单个会话内容输出 Markdown 总结。
要求：
1. 只基于给定内容，不要编造。
2. 总结关键目标、主要改动、风险/异常、结果。
3. 若信息不足，明确指出。

会话 URI: codex://session-001

会话内容：
# Session Dump

## 1. User

Hello"""
    )


def test_maybe_generate_uri_summary_dispatches_rendered_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AIConfig(provider="openai", base_url="https://example.com", model="model", api_key="key")
    session_data = {"messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}]}
    agent = mock.Mock()
    session = mock.Mock()
    request_summary = mock.Mock(return_value="# Summary")
    monkeypatch.setattr("agent_dump.uri_workflow.load_ai_config", lambda: config)
    monkeypatch.setattr("agent_dump.uri_workflow.validate_ai_config", lambda candidate: (candidate is config, []))

    loaded_data, summary = maybe_generate_uri_summary(
        enabled=True,
        output_formats=["json"],
        uri="codex://session-001",
        agent=agent,
        session=session,
        session_data=session_data,
        request_summary=request_summary,
    )

    assert loaded_data is session_data
    assert summary == "# Summary"
    request_summary.assert_called_once()
    called_config, prompt = request_summary.call_args.args
    assert called_config is config
    assert "会话 URI: codex://session-001" in prompt
    assert "## 1. User\n\nHello" in prompt
    agent.get_session_data.assert_not_called()


def test_maybe_generate_uri_summary_returns_loaded_data_when_request_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = AIConfig(provider="openai", base_url="https://example.com", model="model", api_key="key")
    session_data = {"messages": []}
    agent = mock.Mock()
    agent.get_session_data.return_value = session_data
    session = mock.Mock()
    request_summary = mock.Mock(side_effect=RuntimeError("service unavailable"))
    monkeypatch.setattr("agent_dump.uri_workflow.load_ai_config", lambda: config)
    monkeypatch.setattr("agent_dump.uri_workflow.validate_ai_config", lambda candidate: (candidate is config, []))

    loaded_data, summary = maybe_generate_uri_summary(
        enabled=True,
        output_formats=["json"],
        uri="codex://session-001",
        agent=agent,
        session=session,
        session_data=None,
        request_summary=request_summary,
    )

    assert loaded_data is session_data
    assert summary is None
    agent.get_session_data.assert_called_once_with(session)
    assert "AI 总结请求失败: service unavailable" in capsys.readouterr().out
