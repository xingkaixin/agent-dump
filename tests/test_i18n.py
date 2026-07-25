from string import Formatter

import pytest

from agent_dump.i18n import TRANSLATIONS, I18n, Keys


def _placeholder_names(template: str) -> frozenset[str]:
    return frozenset(field_name for _, field_name, _, _ in Formatter().parse(template) if field_name)


def test_translation_catalogs_cover_all_declared_keys() -> None:
    declared_keys = {value for name, value in vars(Keys).items() if name.isupper() and isinstance(value, str)}

    assert set(TRANSLATIONS["en"]) == declared_keys
    assert set(TRANSLATIONS["zh"]) == declared_keys


@pytest.mark.parametrize("key", sorted(TRANSLATIONS["en"]))
def test_translation_placeholders_match_between_languages(key: str) -> None:
    assert _placeholder_names(TRANSLATIONS["en"][key]) == _placeholder_names(TRANSLATIONS["zh"][key])


def test_english_translation_renders_independently_of_global_locale() -> None:
    translator = I18n()
    translator.set_language("en")

    assert (
        translator.t(Keys.URI_EXPORT_SAVED, format="json", path="/tmp/session.json")
        == "✅ Exported session [json] to: /tmp/session.json"
    )


def test_translation_falls_back_to_english_then_key() -> None:
    translator = I18n()
    translator.translations = {"en": {"EN_ONLY": "Hello {name}"}, "zh": {}}
    translator.set_language("zh")

    assert translator.t("EN_ONLY", name="Ada") == "Hello Ada"
    assert translator.t("UNKNOWN") == "UNKNOWN"


# 两语言值刻意相同的 key。用显式白名单而不是启发式：新增 key 时必须在这里做一次决定，
# 而不是被某条规则悄悄放过。
INTENTIONALLY_IDENTICAL_KEYS = frozenset(
    {
        # config.toml 的字段名本身，翻译反而对不上用户要编辑的内容
        "CONFIG_CONFIRM_API_KEY",
        "CONFIG_CONFIRM_BASE_URL",
        "CONFIG_CONFIRM_EXPORT_OUTPUT",
        "CONFIG_CONFIRM_MODEL",
        "CONFIG_CONFIRM_PROVIDER",
        "CONFIG_INPUT_API_KEY",
        "CONFIG_INPUT_BASE_URL",
        "CONFIG_INPUT_MODEL",
        # 纯符号或纯占位符模板
        "CONFIG_INPUT_PROMPT",
        "EXPORT_SUCCESS",
        "EXPORT_SUCCESS_FORMAT",
        "PROVIDERS_ROOT_ROW",
        "PROVIDERS_ROW",
        # 缩写，中文语境同样直接用
        "SEARCH_RESULT_URI",
    }
)


class TestNoUntranslatedValues:
    """AD-138：key/占位符 parity 抓不到「值层面漏译」。"""

    def test_no_key_is_accidentally_left_untranslated(self):
        """zh 值与 en 值完全相同且不在白名单里的 key，就是漏译。

        DIAGNOSTIC_SEARCHED_ROOTS 的 zh 值曾是未翻译的 "searched roots"，
        既有的 key/占位符 parity 测试完全看不到它。
        """
        from agent_dump.i18n import TRANSLATIONS

        en, zh = TRANSLATIONS["en"], TRANSLATIONS["zh"]
        identical = {key for key in en if key in zh and en[key] == zh[key]}

        assert identical - INTENTIONALLY_IDENTICAL_KEYS == set(), (
            "以下 key 的中文值与英文完全相同，疑似漏译；确属刻意相同请加入 "
            f"INTENTIONALLY_IDENTICAL_KEYS: {sorted(identical - INTENTIONALLY_IDENTICAL_KEYS)}"
        )

    def test_the_allowlist_has_no_stale_entries(self):
        """白名单里的 key 若已被翻译或删除，应及时清理，否则它会掩盖将来的漏译。"""
        from agent_dump.i18n import TRANSLATIONS

        en, zh = TRANSLATIONS["en"], TRANSLATIONS["zh"]
        stale = {key for key in INTENTIONALLY_IDENTICAL_KEYS if key not in en or en[key] != zh.get(key)}

        assert stale == set(), f"白名单条目已不再需要: {sorted(stale)}"


class TestStrictFormatting:
    """AD-138：占位符不匹配应在测试期失败，而不是把字面 {days} 交给用户。"""

    def test_placeholder_mismatch_raises_under_strict_mode(self):
        from agent_dump.i18n import I18n

        instance = I18n()
        instance.translations = {"en": {"K": "needs {missing}"}}
        instance.lang = "en"

        with pytest.raises(KeyError):
            instance.t("K", other="x")

    def test_placeholder_mismatch_is_tolerated_in_production_mode(self, monkeypatch):
        """生产实现宁可漏出模板也不要因文案问题崩掉命令。"""
        from agent_dump.i18n import I18n

        monkeypatch.setattr("agent_dump.i18n.STRICT_FORMATTING", False)
        instance = I18n()
        instance.translations = {"en": {"K": "needs {missing}"}}
        instance.lang = "en"

        assert instance.t("K", other="x") == "needs {missing}"
