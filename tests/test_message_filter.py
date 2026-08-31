import pytest

from agent_dump.message_filter import (
    filter_messages_for_export,
    should_filter_message_for_export,
)


@pytest.mark.parametrize(
    "marker",
    [
        "AGENTS.md instructions for /workspace/project",
        "<instructions>",
        "<environment_context>",
        "<permissions instructions>",
        "<collaboration_mode>",
        "<instructions>user-authored XML</instructions>",
        "# AGENTS.md instructions for /workspace\n<instructions>quoted rules</instructions>",
    ],
)
def test_preserves_user_messages_containing_context_markers(marker: str) -> None:
    message = {"role": "USER", "parts": [{"type": "text", "text": marker}]}

    assert should_filter_message_for_export(message) is False


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"role": "developer", "parts": []}, True),
        ({"role": "assistant", "parts": [{"type": "text", "text": "<instructions>"}]}, False),
        ({"role": "user", "parts": [{"type": "text", "text": "Explain this code"}]}, False),
        ({"role": "user", "parts": []}, False),
    ],
)
def test_filters_only_provider_identified_context(message: dict[str, object], expected: bool) -> None:
    assert should_filter_message_for_export(message) is expected


def test_filter_messages_for_export_preserves_order() -> None:
    normal_user = {"role": "user", "parts": [{"type": "text", "text": "Question"}]}
    developer = {"role": "developer", "parts": [{"type": "text", "text": "Policy"}]}
    assistant = {"role": "assistant", "parts": [{"type": "text", "text": "Answer"}]}

    assert filter_messages_for_export([normal_user, developer, assistant]) == [normal_user, assistant]
