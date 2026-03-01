"""
Shared message filtering helpers.
"""

DEVELOPER_LIKE_USER_MARKERS = (
    "agents.md instructions for",
    "<instructions>",
    "<environment_context>",
    "<permissions instructions>",
    "<collaboration_mode>",
)


def get_text_content_parts(message: dict) -> list[str]:
    """Extract text-like parts from a message."""
    content_parts: list[str] = []
    parts = message.get("parts", [])

    for part in parts:
        part_type = part.get("type")
        if part_type in ("text", "reasoning"):
            text = str(part.get("text", "")).strip()
            if text:
                content_parts.append(text)
        elif part_type == "plan":
            text = str(part.get("input", "")).strip()
            if text:
                content_parts.append(text)

    return content_parts


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

    content_parts = get_text_content_parts(message)
    return is_developer_like_user_message(role_normalized, content_parts)


def filter_messages_for_export(messages: list[dict]) -> list[dict]:
    """Filter out injected/system messages while keeping normal conversation/tool data."""
    return [message for message in messages if not should_filter_message_for_export(message)]
