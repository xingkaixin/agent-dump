"""Tests for text_safety.py —— 不可信会话文本的输出净化。"""

import pytest

from agent_dump.text_safety import (
    DISPLAY_TEXT_LIMIT,
    has_unsafe_body_characters,
    has_unsafe_line_characters,
    safe_body_text,
    safe_display_text,
)

# 只描述被剥离的字符类别，不构造可运行的终端指令
ANSI_ERASE_LINE = "\x1b[2K"
OSC_HYPERLINK_START = "\x1b]8;;"
BIDI_RTL_OVERRIDE = "‮"
CARRIAGE_RETURN = "\r"


class TestSafeBodyText:
    @pytest.mark.parametrize(
        "text",
        [
            "普通中文与 ascii 混排",
            "emoji 🎉 保留",
            "日本語のテキスト",
            "line1\nline2",
            "col1\tcol2",
            "",
        ],
    )
    def test_legitimate_content_is_untouched(self, text):
        """CJK、emoji、换行、制表都是正当内容，不能被误伤。"""
        assert safe_body_text(text) == text

    @pytest.mark.parametrize(
        "raw",
        [ANSI_ERASE_LINE, OSC_HYPERLINK_START, BIDI_RTL_OVERRIDE, CARRIAGE_RETURN, "\x00", "\x9b", "\x7f"],
    )
    def test_control_and_bidi_characters_are_removed(self, raw):
        result = safe_body_text(f"before{raw}after")

        assert not has_unsafe_body_characters(result)
        assert "before" in result and "after" in result

    def test_body_text_is_not_length_capped(self):
        """导出必须完整，正文不设上限。"""
        long_text = "内容" * 10_000

        assert safe_body_text(long_text) == long_text


class TestSafeDisplayText:
    def test_collapses_newlines_into_one_line(self):
        assert safe_display_text("line1\nline2\tline3") == "line1 line2 line3"

    def test_collapses_repeated_whitespace(self):
        assert safe_display_text("a     b\n\n\nc") == "a b c"

    @pytest.mark.parametrize("raw", [ANSI_ERASE_LINE, OSC_HYPERLINK_START, BIDI_RTL_OVERRIDE, CARRIAGE_RETURN])
    def test_control_sequences_cannot_survive(self, raw):
        result = safe_display_text(f"title{raw}suffix")

        assert not has_unsafe_body_characters(result)
        assert "\n" not in result and "\r" not in result

    def test_long_text_is_capped_with_a_marker(self):
        """否则一个超长「标题」就能把列表输出冲掉。"""
        result = safe_display_text("x" * (DISPLAY_TEXT_LIMIT * 3))

        assert len(result) == DISPLAY_TEXT_LIMIT
        assert result.endswith("…")

    def test_text_at_the_limit_is_not_truncated(self):
        exact = "y" * DISPLAY_TEXT_LIMIT

        assert safe_display_text(exact) == exact

    def test_cjk_is_preserved_within_the_cap(self):
        assert safe_display_text("修复登录超时") == "修复登录超时"


class TestUnsafeCharacterPredicates:
    """两个谓词分别与两个净化函数的字符集对齐。"""

    @pytest.mark.parametrize("text", ["plain", "中文", "with\nnewline", "with\ttab", ""])
    def test_body_predicate_allows_newlines_and_tabs(self, text):
        assert not has_unsafe_body_characters(text)

    @pytest.mark.parametrize("text", ["a\x1bb", "a\rb", "a\x00b", f"a{BIDI_RTL_OVERRIDE}b"])
    def test_body_predicate_rejects_control_and_bidi(self, text):
        assert has_unsafe_body_characters(text)

    @pytest.mark.parametrize("text", ["with\nnewline", "with\ttab", "with\rreturn"])
    def test_line_predicate_is_stricter(self, text):
        """文件名与单行展示不能容忍换行：带 CR 的文件名被回显时也能改写终端。"""
        assert has_unsafe_line_characters(text)
        assert not has_unsafe_body_characters(text) or "\r" in text

    @pytest.mark.parametrize("text", ["plain", "中文", "session-id-1", ""])
    def test_line_predicate_allows_ordinary_text(self, text):
        assert not has_unsafe_line_characters(text)


# 覆盖 C0、C1、OSC、CR/LF 与 bidi override 五类攻击字符
ESC_CLEAR_LINE = "\x1b[2K\rINJECTED"
OSC_TITLE = "\x1b]0;pwned\x07"
C1_CONTROL = "\x9b"
BIDI_OVERRIDE = "‮"
POISON = f"real{ESC_CLEAR_LINE}{OSC_TITLE}{C1_CONTROL}{BIDI_OVERRIDE}"


class TestRemainingTerminalFieldsAreSanitized:
    """AD-165：所有进入终端的动态标量都要经过净化，程序自身的布局要保留。"""

    def test_diagnostic_strips_every_dynamic_field(self):
        from agent_dump.diagnostics import DiagnosticError, ParsedUri, render_diagnostic
        from agent_dump.i18n import i18n

        error = DiagnosticError(
            summary=f"summary {POISON}",
            parsed_uri=ParsedUri(raw=f"evil://{POISON}", scheme=f"s{POISON}", session_id=f"id{POISON}"),
            details=(f"detail {POISON}",),
            searched_roots=(f"/root/{POISON}",),
            capability_gap=f"gap {POISON}",
            next_steps=(f"step {POISON}",),
        )

        rendered = render_diagnostic(error, t=i18n.t)

        assert not has_unsafe_body_characters(rendered)
        assert "INJECTED" in rendered, "内容本身要保留，被移除的只是控制字符"
        # diagnostic 自己的 bullets 与分行是程序布局，不能被压平
        assert rendered.count("\n") >= 6
        assert "  - " in rendered

    def test_provider_warning_is_one_safe_line(self, tmp_path, capsys):
        from agent_dump.i18n import Keys, i18n

        message = i18n.t(
            Keys.WARN_SESSION_PARSE_FAILED,
            path=safe_display_text(f"/tmp/{POISON}"),
            error=safe_display_text(f"boom {POISON}"),
        )

        assert not has_unsafe_line_characters(message)
        assert "\n" not in message

    def test_body_text_keeps_markdown_layout(self):
        markdown = f"# Title{ESC_CLEAR_LINE}\n\n- item one\n- item {OSC_TITLE}two\n\n```py\nx = 1\n```\n"

        safe = safe_body_text(markdown)

        assert not has_unsafe_body_characters(safe)
        assert safe.count("\n") == markdown.count("\n"), "Markdown 换行全部保留，被移除的只有控制字符"
        assert "```py\nx = 1\n```" in safe
        assert "- item one" in safe

    def test_display_text_collapses_only_the_scalar(self):
        collapsed = safe_display_text(f"line one{ESC_CLEAR_LINE}\nline two")

        assert not has_unsafe_line_characters(collapsed)
        assert "\n" not in collapsed, "单行字段里的换行本身就是攻击面"
