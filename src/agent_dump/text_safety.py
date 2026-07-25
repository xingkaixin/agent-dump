"""Sanitizers for third-party session text before it reaches a terminal or a file.

会话标题、消息正文、工具参数都由别的工具写入，属于不可信数据。其中的控制字符在
终端和 Markdown 里都没有正当用途，却能改写已打印的行、让某个会话在列表里隐身、
伪造诊断块，或经 OSC 序列改变用户对「导出了什么」的认知。

刻意不做的事：不转义 Markdown 语法。导出的意义就是忠实还原会话，而正文里出现
`## 3. User` 这种伪造标题对任何读者都是可见的，与不可见的 ANSI 转义不是一类问题。
"""

import re

# C0（除 \t \n）与 C1 控制字符：ANSI/OSC 转义序列都以这些字符开头
_CONTROL_CHARS = r"\x00-\x08\x0b-\x1f\x7f-\x9f"
# 双向文本覆盖与不可见格式字符：可以让显示顺序与实际内容不一致
_BIDI_OVERRIDES = r"؜‎‏‪-‮⁦-⁩"

_UNSAFE_IN_BODY = re.compile(f"[{_CONTROL_CHARS}{_BIDI_OVERRIDES}]")
_UNSAFE_IN_LINE = re.compile(f"[{_CONTROL_CHARS}\t\n\r{_BIDI_OVERRIDES}]")

# 单行展示的长度上限。没有它，一个 100KB 的「标题」就能把列表输出冲掉。
DISPLAY_TEXT_LIMIT = 500
_TRUNCATION_MARKER = "…"


def safe_body_text(text: str) -> str:
    """Strip characters that can rewrite a terminal or forge structure in a file.

    保留 \\t 与 \\n，正文的换行与缩进是内容的一部分；不限长，导出必须完整。
    """
    return _UNSAFE_IN_BODY.sub("", text)


def safe_display_text(text: str, *, limit: int = DISPLAY_TEXT_LIMIT) -> str:
    """Collapse untrusted text into one bounded, control-free line."""
    collapsed = " ".join(_UNSAFE_IN_LINE.sub(" ", text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER


def has_unsafe_body_characters(text: str) -> bool:
    """Whether text holds characters safe_body_text would strip.

    与 safe_body_text 同一字符集：\t 与 \n 在正文里是正当内容，不算不安全。
    """
    return _UNSAFE_IN_BODY.search(text) is not None


def has_unsafe_line_characters(text: str) -> bool:
    """Whether text holds characters safe_display_text would strip.

    比 has_unsafe_body_characters 更严，额外包含 \t\n\r。文件名与单行展示用这个：
    一个带 CR 的文件名被回显时同样能改写终端已输出的内容。
    """
    return _UNSAFE_IN_LINE.search(text) is not None
