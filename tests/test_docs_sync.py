"""Guards against documentation drifting from the code (AD-144).

AD-119 已经手工同步过一次 README 的结构树，几个月后 AGENTS.md 又漂了 10 个模块。
手工同步会再漂，所以这里把「文档与代码一致」变成 CI 检查。
"""

from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")


def _source_modules() -> set[str]:
    return {path.name for path in (REPO_ROOT / "src" / "agent_dump").rglob("*.py")}


class TestAgentsMdTreeCoversEveryModule:
    def test_project_tree_lists_every_source_module(self):
        missing = sorted(name for name in _source_modules() if name not in AGENTS_MD)

        assert missing == [], f"AGENTS.md 的项目结构树缺少这些模块: {missing}"

    def test_internal_module_table_covers_non_public_modules(self):
        """§2.2 是内部实现清单；公开 API（§2.1）与 provider 实现另有章节。"""
        table = AGENTS_MD[AGENTS_MD.index("### 2.2 内部实现") : AGENTS_MD.index("### 2.3")]
        public_or_provider = {
            "__init__.py",
            "__about__.py",
            "__main__.py",
            "base.py",
            "opencode.py",
            "zcode.py",
            "codex.py",
            "kimi.py",
            "claudecode.py",
            "cursor.py",
            "pi.py",
            "title_fallback.py",
            "i18n.py",
            "diagnostics.py",
            "scanner.py",
            "paths.py",
            "message_filter.py",
            "collect_models.py",
        }
        expected = {name for name in _source_modules() if name not in public_or_provider}
        missing = sorted(name for name in expected if name not in table)

        assert missing == [], f"AGENTS.md §2.2 缺少这些内部模块: {missing}"

    def test_declared_line_length_matches_ruff(self):
        """文档写 100 而 ruff 配 120 时，照文档写的 agent 会按错的宽度换行。"""
        ruff = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
        configured = re.search(r"line-length = (\d+)", ruff)

        assert configured is not None
        assert f"单行最大长度 {configured.group(1)}" in AGENTS_MD


class TestReadmeDocumentsEveryCliFlag:
    """README 的表格自称 "Full Parameter Reference"，漏掉的 flag 会被读成「不存在」。"""

    @staticmethod
    def _declared_option_strings() -> set[str]:
        source = (REPO_ROOT / "src" / "agent_dump" / "cli.py").read_text(encoding="utf-8")
        return set(re.findall(r'add_argument\(\s*"(--?[a-z0-9-]+)"', source))

    @pytest.mark.parametrize("readme", ["README.md", "README_zh.md"])
    def test_every_flag_appears(self, readme):
        content = (REPO_ROOT / readme).read_text(encoding="utf-8")
        missing = sorted(flag for flag in self._declared_option_strings() if flag not in content)

        assert missing == [], f"{readme} 未记录这些 CLI 参数: {missing}"


class TestChangelogLinksResolve:
    def test_english_changelog_symlink_is_not_self_referential(self):
        """曾经指向字面量 "CHANGELOG.md"，相对自身目录解析即指向自己，在每个 clone 里都是坏的。"""
        link = REPO_ROOT / "docs" / "en" / "CHANGELOG.md"
        if not link.is_symlink():
            pytest.skip("docs/en/CHANGELOG.md 不是符号链接")

        assert link.exists(), f"符号链接无法解析: -> {link.readlink()}"
        assert link.resolve() != link, "符号链接指向自己"

    def test_chinese_changelog_is_a_real_file(self):
        assert (REPO_ROOT / "docs" / "zh" / "CHANGELOG.md").is_file()
