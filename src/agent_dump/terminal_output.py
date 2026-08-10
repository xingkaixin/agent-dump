"""Safe composition for one-line terminal messages."""

from agent_dump.i18n import i18n
from agent_dump.text_safety import safe_display_text


def render_terminal_message(key: str, /, **fields: object) -> str:
    """Render an i18n message after sanitizing every dynamic field."""
    safe_fields = {name: safe_display_text(str(value)) for name, value in fields.items()}
    return i18n.t(key, **safe_fields)
