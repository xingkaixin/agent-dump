"""
Shared message filtering helpers.

「这条消息里有什么」由 transcript 回答；这里只保留「哪些消息不该导出」这条产品策略。
"""

from agent_dump.transcript import read_message

DEVELOPER_LIKE_USER_MARKERS = (
    "agents.md instructions for",
    "<instructions>",
    "<environment_context>",
    "<permissions instructions>",
    "<collaboration_mode>",
)


def is_developer_like_user_message(role_normalized: str, content_parts: list[str]) -> bool:
    """Detect user messages that are actually injected system/developer context."""
    if role_normalized != "user" or not content_parts:
        return False

    combined_text = "\n".join(content_parts).lower()
    return any(marker in combined_text for marker in DEVELOPER_LIKE_USER_MARKERS)


def should_filter_message_for_export(message: dict) -> bool:
    """Whether a message should be filtered from exported JSON."""
    role_normalized = str(message.get("role", "unknown")).lower()
    if role_normalized == "developer":
        return True

    return is_developer_like_user_message(role_normalized, list(read_message(message).texts))


def filter_messages_for_export(messages: list[dict]) -> list[dict]:
    """Filter out injected/system messages while keeping normal conversation/tool data."""
    return [message for message in messages if not should_filter_message_for_export(message)]
