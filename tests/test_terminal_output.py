from agent_dump.i18n import Keys
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import has_unsafe_line_characters


def test_render_terminal_message_sanitizes_each_dynamic_field():
    poison = "value\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"

    rendered = render_terminal_message(
        Keys.EXPORT_ERROR_FORMAT,
        title=poison,
        format=poison,
        error=RuntimeError(poison),
    )

    assert not has_unsafe_line_characters(rendered)
    assert "FORGED" in rendered
