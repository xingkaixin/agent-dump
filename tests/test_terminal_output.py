from io import BytesIO, TextIOWrapper

from agent_dump.i18n import Keys
from agent_dump.terminal_output import configure_standard_stream_encoding, render_terminal_message
from agent_dump.text_safety import has_unsafe_line_characters


def test_configure_standard_stream_encoding_writes_windows_unicode_as_utf8():
    output_bytes = BytesIO()
    output = TextIOWrapper(output_bytes, encoding="cp1252")

    configure_standard_stream_encoding("win32", (output,))
    output.write("✅")
    output.flush()

    assert output.encoding == "utf-8"
    assert output_bytes.getvalue() == "✅".encode()


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
