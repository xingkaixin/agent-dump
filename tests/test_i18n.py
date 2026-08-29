from string import Formatter

import pytest

from agent_dump.i18n import TRANSLATIONS, I18n, Keys, _detect_environment_language


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


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"LANG": "zh_CN.UTF-8", "LC_ALL": "C"}, "en"),
        ({"LANG": "en_US.UTF-8", "LC_MESSAGES": "zh_CN.UTF-8"}, "zh"),
        ({"LANG": "zh_CN.UTF-8", "LC_MESSAGES": "en_US.UTF-8"}, "en"),
        ({"LANG": "en_US.UTF-8", "LC_MESSAGES": "en_US.UTF-8", "LC_ALL": "zh_TW.UTF-8"}, "zh"),
        ({}, None),
    ],
)
def test_environment_language_uses_posix_precedence(environ: dict[str, str], expected: str | None) -> None:
    assert _detect_environment_language(environ) == expected


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


class TestCatalogHasNoUnreferencedKeys:
    """AD-142：死 key 每个都要在 Keys/en/zh 三处同步维护，parity 测试还会强制这份维护。"""

    def test_every_key_is_referenced_outside_the_catalog(self):
        """目录定义之外没有任何引用的 key 就是死 key。

        不含 key/语言目录自身，也不含本测试文件（白名单会提到 key 名）。
        """
        from pathlib import Path

        from agent_dump.i18n import Keys

        repo_root = Path(__file__).resolve().parent.parent
        sources = [
            path
            for path in list((repo_root / "src").rglob("*.py")) + list((repo_root / "tests").rglob("*.py"))
            if path.name not in {"i18n.py", "i18n_en.py", "i18n_keys.py", "i18n_zh.py", "test_i18n.py"}
        ]
        blob = "\n".join(path.read_text(encoding="utf-8") for path in sources)

        declared = {name for name in dir(Keys) if name.isupper()}
        unreferenced = {name for name in declared if name not in blob}

        assert unreferenced == set(), f"以下 i18n key 已无引用，应删除: {sorted(unreferenced)}"


# 允许保留中文字面量的模块，各有明确理由。新增条目必须写清为什么。
CHINESE_LITERAL_EXEMPTIONS = {
    # 发给模型的 prompt 文本与匹配中文的正则：属于算法输入，按 locale 改写会改变
    # 模型输出质量（见 AD-138 / AD-146 的范围说明）
    "collect_events.py",
    "collect_llm.py",
    "collect_prompts.py",
    "prompt_safety.py",
    "uri_workflow.py",
    # i18n 目录本身
    "i18n.py",
    "i18n_zh.py",
}


class TestNoUserFacingChineseOutsideTheCatalog:
    """AD-146：用户可见文案必须走 i18n，否则 en locale 的用户会拿到中文。"""

    @staticmethod
    def _chinese_string_literals(path) -> list[tuple[int, str]]:
        """带中文的字符串字面量，排除 docstring 与 i18n.t(...) 的参数。

        用 ast 而不是正则扫行：docstring 里出现中文（解释性文字、举例）是正常的，
        按行匹配区分不了它和真正会被打印的字面量。
        """
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        localized = {
            id(arg)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "t"
            for arg in list(node.args) + [kw.value for kw in node.keywords]
        }

        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings or id(node) in localized:
                continue
            # 单字符字面量是区间边界常量（如 search_index 的 CJK 范围），不会是 UI 文案；
            # ast 会把 "\u4e00" 这类转义解析成实际字符，按长度过滤比按写法过滤可靠
            if len(node.value) < 2:
                continue
            if any("\u4e00" <= char <= "\u9fff" for char in node.value):
                hits.append((node.lineno, node.value))
        return sorted(hits)

    def test_no_module_holds_unexplained_chinese_literals(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        offenders: list[str] = []
        for path in sorted((repo_root / "src" / "agent_dump").rglob("*.py")):
            if path.name in CHINESE_LITERAL_EXEMPTIONS:
                continue
            for lineno, text in self._chinese_string_literals(path):
                offenders.append(f"{path.relative_to(repo_root)}:{lineno}: {text[:40]}")

        assert offenders == [], (
            "以下中文字面量未走 i18n；确属 prompt/正则等非 UI 用途请加入 "
            "CHINESE_LITERAL_EXEMPTIONS 并注明理由:\n  " + "\n  ".join(offenders)
        )

    def test_exemptions_are_all_real_modules(self):
        """模块被删或改名后，豁免条目要清掉，否则会掩盖新问题。"""
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "src" / "agent_dump"
        existing = {path.name for path in src.rglob("*.py")}
        stale = sorted(CHINESE_LITERAL_EXEMPTIONS - existing)

        assert stale == [], f"豁免列表中的模块已不存在: {stale}"
