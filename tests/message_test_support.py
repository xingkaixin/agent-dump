from agent_dump.agents.message_types import NormalizedPart, TextPart, ToolPart, is_text_part, is_tool_part


def require_text_part(part: NormalizedPart) -> TextPart:
    assert is_text_part(part)
    return part


def require_tool_part(part: NormalizedPart) -> ToolPart:
    assert is_tool_part(part)
    return part
