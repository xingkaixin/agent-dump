"""Locale-neutral assertion helpers for CLI output (AD-137).

套件此前把 conftest 的 autouse fixture 恒定为 zh，于是数百条断言直接匹配中文字面量。
两重代价互相加固：多数用户实际拿到的 en 路径从未被任何工作流验证过，而套件被焊死在
中文文案上，让 i18n 改动变成大规模测试改写——这本身又成了不去修 i18n 覆盖的阻力。

这里提供的是机制，不是一次性改写：
- `use_language` fixture 让单个测试切到指定 locale
- `expect(key, **kwargs)` 按当前 locale 解析期望文案，替代硬编码字面量
- `ALL_LANGUAGES` 供 [zh, en] 参数化

既有的中文字面量断言保持原样——autouse fixture 仍默认 zh。新增或触及 i18n 文案的
测试应改用 expect()。
"""

from agent_dump.i18n import Keys, i18n

ALL_LANGUAGES = ("zh", "en")

__all__ = ["ALL_LANGUAGES", "Keys", "expect", "expect_contains"]


def expect(key: str, **kwargs: object) -> str:
    """Resolve the expected user-facing message for the currently active locale."""
    return i18n.t(key, **kwargs)


def expect_contains(haystack: str, key: str, **kwargs: object) -> bool:
    """Whether output contains the message for `key` in the active locale.

    i18n 文案常带 emoji 与换行；这里比对去掉首尾空白后的整串，避免用截断的片段
    误判命中。
    """
    return expect(key, **kwargs).strip() in haystack
