"""Guards against documentation drifting from the code (AD-144).

AD-119 已经手工同步过一次 README 的结构树，几个月后 AGENTS.md 又漂了 10 个模块。
手工同步会再漂，所以这里把「文档与代码一致」变成 CI 检查。
"""

import json
from pathlib import Path
import re
import shlex

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
# 两份 README 的架构地图是贡献者判断「逻辑该放哪」的依据；AGENTS.md 才是详细约束来源
CONTRIBUTOR_MAPS = ("README.md", "README_zh.md")


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

    @pytest.mark.parametrize("doc", CONTRIBUTOR_MAPS)
    def test_readme_structure_tree_lists_every_source_module(self, doc):
        """AD-119 手工同步过一次，AGENTS.md 有门禁而 README 没有，于是只有 README 又漂了。"""
        content = (REPO_ROOT / doc).read_text(encoding="utf-8")
        missing = sorted(name for name in _source_modules() if name not in content)

        assert missing == [], f"{doc} 的项目结构树缺少这些模块: {missing}"

    def test_both_readmes_describe_the_same_modules(self):
        """一份加了模块另一份没加，两种语言的读者会看到不同的架构。"""
        modules = _source_modules()
        english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        chinese = (REPO_ROOT / "README_zh.md").read_text(encoding="utf-8")

        only_english = sorted(name for name in modules if name in english and name not in chinese)
        only_chinese = sorted(name for name in modules if name in chinese and name not in english)

        assert (only_english, only_chinese) == ([], []), (
            f"只在 README.md 里: {only_english}；只在 README_zh.md 里: {only_chinese}"
        )

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


class TestNpmWrapperRuntimeContract:
    @staticmethod
    def _manifest() -> dict:
        return json.loads((REPO_ROOT / "npm" / "packages" / "cli" / "package.json").read_text(encoding="utf-8"))

    def test_wrapper_entrypoint_and_manifest_require_the_same_node_runtime(self):
        manifest = self._manifest()
        entrypoint = (REPO_ROOT / "npm" / "packages" / "cli" / "bin" / "agent-dump.cjs").read_text(encoding="utf-8")

        assert manifest["engines"]["node"] == ">=22"
        assert entrypoint.startswith("#!/usr/bin/env node\n")

    @pytest.mark.parametrize(
        "document",
        [
            "README.md",
            "README_zh.md",
            "npm/packages/cli/README.md",
            "skills/agent-dump/SKILL.md",
            "web/src/lib/i18n.ts",
        ],
    )
    def test_every_bun_entrypoint_declares_the_node_minimum(self, document):
        content = (REPO_ROOT / document).read_text(encoding="utf-8")

        assert "bunx" in content
        assert "Node.js 22" in content


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


class TestLandingPageMatchesTheRealCli:
    """AD-177：landing page 自称是 truthful preview，那它的行为声明就得是真的。

    只锁真实 CLI 的不变量——命令、字段标签、默认输出根、Provider URI scheme。
    颜色、时间戳、排名数值这些会随环境变化，不进断言。
    """

    SCENES = (REPO_ROOT / "web" / "src" / "lib" / "i18n.ts").read_text(encoding="utf-8")

    @staticmethod
    def _scene_block() -> str:
        content = TestLandingPageMatchesTheRealCli.SCENES
        start = content.index("export const terminalScenes")
        return content[start : content.index("];", start)]

    def test_every_previewed_flag_exists_in_the_cli(self):
        """预览里的 flag 从 cli.py 的 add_argument 校验，不在测试里重建一份参数表。"""
        cli_source = (REPO_ROOT / "src" / "agent_dump" / "cli.py").read_text(encoding="utf-8")
        declared = set(re.findall(r'add_argument\(\s*"(-{1,2}[a-z-]+)"', cli_source))
        declared |= set(re.findall(r'add_argument\("[^"]+",\s*"(-{1,2}[a-z-]+)"', cli_source))

        block = self._scene_block()
        commands = re.findall(r"command: [\"'](agent-dump [^\"']+)[\"']", block)
        assert commands, "至少要有一个终端场景"

        for command in commands:
            for token in shlex.split(command)[1:]:
                if token.startswith("-"):
                    assert token in declared, f"{command!r} 用了 CLI 没有的参数 {token}"

    def test_the_markdown_scene_uses_the_real_default_output_root(self):
        from agent_dump.cli_shared import DEFAULT_OUTPUT_BASE_DIR

        block = self._scene_block()
        root = DEFAULT_OUTPUT_BASE_DIR.name

        assert f"{root}/codex/" in block, (
            f"未传 --output 时导出落在 {DEFAULT_OUTPUT_BASE_DIR}/<provider>/，预览不能写别的路径"
        )
        assert "./exports/" not in block, "./exports 不是任何默认路径"

    def test_previewed_uris_use_registered_schemes(self):
        from agent_dump.agent_registry import AGENT_REGISTRATIONS

        registered = {scheme for reg in AGENT_REGISTRATIONS for scheme in reg.uri_schemes}
        block = self._scene_block()
        previewed = set(re.findall(r"([a-z][a-z0-9]*)://", block))

        unknown = sorted(previewed - registered)
        assert unknown == [], f"预览里出现了未注册的 URI scheme: {unknown}"

    def test_interactive_scene_shows_the_two_stage_selection(self, use_language):
        """真实流程是先选 Provider 再选该 Provider 的会话，不是跨 Provider 的单一列表。"""
        from agent_dump.i18n import Keys, i18n

        use_language("en")
        agent_prompt = i18n.t(Keys.SELECT_AGENT_PROMPT)
        sessions_header = i18n.t(Keys.AVAILABLE_SESSIONS)

        block = self._scene_block()
        assert agent_prompt in block, "缺少选择 Provider 这一步"
        assert sessions_header in block
        assert block.index(agent_prompt) < block.index(sessions_header), "Provider 选择在会话列表之前"

    def test_search_scene_uses_the_real_header_and_labels(self, use_language):
        from agent_dump.i18n import Keys, i18n

        use_language("en")
        header = i18n.t(Keys.SEARCH_HEADER, days=7, query="auth timeout").strip().lstrip("🔎 ")

        block = self._scene_block()
        assert header in block, f"search header 与 CLI 不一致，实际是: {header!r}"
        assert "ranked by relevance" not in block, "renderer 不打印这一行"
        for label in ("Provider:", "URI:", "Snippet:"):
            assert label in block, f"search 结果缺少真实字段标签 {label}"
