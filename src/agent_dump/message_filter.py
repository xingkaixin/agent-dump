"""
Shared message filtering helpers.

「这条消息里有什么」由 transcript 回答；这里只保留「哪些消息不该导出」这条产品策略。
"""


def should_filter_message_for_export(message: dict) -> bool:
    """Filter context identified by the provider without interpreting user text."""
    return str(message.get("role", "unknown")).lower() == "developer"


def filter_messages_for_export(messages: list[dict]) -> list[dict]:
    """Filter out injected/system messages while keeping normal conversation/tool data."""
    return [message for message in messages if not should_filter_message_for_export(message)]
