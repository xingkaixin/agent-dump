"""Safe composition for one-line terminal messages."""

from typing import TextIO

from agent_dump.i18n import i18n
from agent_dump.text_safety import safe_display_text


def configure_standard_stream_encoding(platform: str, streams: tuple[TextIO, ...]) -> None:
    """Use UTF-8 for Windows output so redirected Unicode text remains writable."""
    if platform != "win32":
        return

    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def render_terminal_message(key: str, /, **fields: object) -> str:
    """Render an i18n message after sanitizing every dynamic field."""
    safe_fields = {name: safe_display_text(str(value)) for name, value in fields.items()}
    return i18n.t(key, **safe_fields)
