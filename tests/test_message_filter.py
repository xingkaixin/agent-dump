import pytest

from agent_dump.message_filter import (
    filter_messages_for_export,
    get_text_content_parts,
    should_filter_message_for_export,
)


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ({"type": "text", "text": "  user text  "}, ["user text"]),
        ({"type": "reasoning", "text": "  model reasoning  "}, ["model reasoning"]),
        ({"type": "plan", "input": "  implementation plan  "}, ["implementation plan"]),
        ({"type": "tool", "text": "ignored tool output"}, []),
        ({"type": "text", "text": "   "}, []),
        ({"text": "missing type"}, []),
    ],
)
def test_get_text_content_parts_handles_supported_part_types(part: dict[str, str], expected: list[str]) -> None:
    assert get_text_content_parts({"parts": [part]}) == expected


@pytest.mark.parametrize(
    "marker",
    [
        "AGENTS.md instructions for /workspace/project",
        "<instructions>",
        "<environment_context>",
        "<permissions instructions>",
        "<collaboration_mode>",
    ],
)
def test_filters_each_injected_context_marker(marker: str) -> None:
    message = {"role": "USER", "parts": [{"type": "text", "text": marker}]}

    assert should_filter_message_for_export(message) is True


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"role": "developer", "parts": []}, True),
        ({"role": "assistant", "parts": [{"type": "text", "text": "<instructions>"}]}, False),
        ({"role": "user", "parts": [{"type": "text", "text": "Explain this code"}]}, False),
        ({"role": "user", "parts": []}, False),
    ],
)
def test_filters_only_developer_and_injected_user_messages(message: dict[str, object], expected: bool) -> None:
    assert should_filter_message_for_export(message) is expected


def test_filter_messages_for_export_preserves_order() -> None:
    normal_user = {"role": "user", "parts": [{"type": "text", "text": "Question"}]}
    developer = {"role": "developer", "parts": [{"type": "text", "text": "Policy"}]}
    assistant = {"role": "assistant", "parts": [{"type": "text", "text": "Answer"}]}

    assert filter_messages_for_export([normal_user, developer, assistant]) == [normal_user, assistant]
