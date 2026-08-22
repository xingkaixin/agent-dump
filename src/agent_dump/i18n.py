"""Internationalization support for agent-dump."""

import locale
import os

from agent_dump.i18n_en import EN_TRANSLATIONS
from agent_dump.i18n_keys import Keys
from agent_dump.i18n_zh import ZH_TRANSLATIONS

__all__ = ("I18n", "Keys", "TRANSLATIONS", "i18n", "setup_i18n")

TRANSLATIONS = {
    "en": EN_TRANSLATIONS,
    "zh": ZH_TRANSLATIONS,
}

# 测试期置 True（见 tests/conftest.py），让 t() 的占位符不匹配直接抛错
STRICT_FORMATTING = False


class I18n:
    def __init__(self) -> None:
        self.lang = "en"
        self.translations = TRANSLATIONS

    def set_language(self, lang: str) -> None:
        if lang in self.translations:
            self.lang = lang
        else:
            # Fallback to English if not supported
            self.lang = "en"

    def detect_language(self) -> str:
        # Check environment variables first
        lang = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
        if "zh" in lang.lower():
            return "zh"

        # Check locale
        try:
            loc = locale.getdefaultlocale()
            if loc and loc[0] and "zh" in loc[0].lower():
                return "zh"
        except Exception:  # noqa: S110
            pass

        return "en"

    def t(self, key: str, **kwargs: object) -> str:
        lang_dict = self.translations.get(self.lang, {})
        msg = lang_dict.get(key)

        if msg is None:
            # Fallback to English
            msg = self.translations.get("en", {}).get(key, key)

        # Should strictly be a string if keys are managed correctly,
        # but for type safety we ensure it is not None.
        if msg is None:
            msg = key

        if kwargs:
            try:
                return msg.format(**kwargs)
            except KeyError:
                # 生产环境宁可漏出模板也不要因文案问题崩掉命令；测试期开启严格模式，
                # 让占位符不匹配在 CI 失败，而不是把字面 {days} 交给用户
                if STRICT_FORMATTING:
                    raise
                return msg
        return msg


# Global instance
i18n = I18n()


def setup_i18n(lang_arg: str | None = None) -> None:
    """
    Initialize i18n with detection logic.
    Priority:
    1. Command line argument (--lang)
    2. Environment variables / Locale
    3. Default (en)
    """
    if lang_arg:
        i18n.set_language(lang_arg)
        return

    detected = i18n.detect_language()
    i18n.set_language(detected)
