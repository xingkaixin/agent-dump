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
