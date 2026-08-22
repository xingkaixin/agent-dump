"""Collect compatibility-entry request tests."""

import io
import json
from unittest import mock

import pytest

from agent_dump.collect import (
    request_summary_from_llm,
)
from agent_dump.config import AIConfig


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
        response.read.side_effect = io.BytesIO(json.dumps(payload).encode("utf-8")).read
        response.__enter__.return_value = response
        response.__exit__.return_value = None

        with mock.patch("agent_dump.collect_llm._open_url", return_value=response):
            result = request_summary_from_llm(config, "prompt")

        assert result == "# summary"

    def test_request_summary_api_error(self):
        config = AIConfig(
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-7-sonnet",
            api_key="ak-test",
        )
        with (
            mock.patch("agent_dump.collect_llm._open_url", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            request_summary_from_llm(config, "prompt")
