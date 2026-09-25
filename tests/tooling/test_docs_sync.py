"""Guards against documentation drifting from the code (AD-144)."""

import json
from pathlib import Path
import re
import shlex

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
DEVELOPMENT_GUIDE = (REPO_ROOT / "docs" / "development-guide.md").read_text(encoding="utf-8")
AGENT_REFERENCE_PATHS = (
    "CONTEXT.md",
    "docs/architecture.md",
    "docs/development-guide.md",
    "docs/release-guide.md",
    "skills/agent-dump/SKILL.md",
    "skills/agent-dump/references/cli-recipes.md",
)


class TestAgentInstructionRouting:
    @pytest.mark.parametrize("relative_path", AGENT_REFERENCE_PATHS)
    def test_agents_md_routes_to_existing_reference(self, relative_path: str) -> None:
        assert f"`{relative_path}`" in AGENTS_MD
        assert (REPO_ROOT / relative_path).is_file()

    def test_declared_line_length_matches_ruff(self) -> None:
        """文档写 100 而 ruff 配 120 时，照文档写的 agent 会按错的宽度换行。"""
        ruff = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
        configured = re.search(r"line-length = (\d+)", ruff)

        assert configured is not None
        assert f"单行最大长度 {configured.group(1)}" in DEVELOPMENT_GUIDE


class TestReadmeDocumentsEveryCliFlag:
    """README 的表格自称 "Full Parameter Reference"，漏掉的 flag 会被读成「不存在」。"""

    @staticmethod
    def _declared_option_strings(cli) -> set[str]:
        result = cli.run("rust", "--help", "--lang", "en")
        assert result.returncode == 0
        return set(re.findall(r"(?<![a-z0-9-])(--?[a-z][a-z0-9-]*)", result.stdout))

    @pytest.mark.parametrize("readme", ["README.md", "README_zh.md"])
    def test_every_flag_appears(self, cli, readme):
        content = (REPO_ROOT / readme).read_text(encoding="utf-8")
        missing = sorted(flag for flag in self._declared_option_strings(cli) if flag not in content)

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


class TestWebDeploymentTooling:
    def test_wrangler_is_exactly_pinned_and_invoked_locally(self) -> None:
        manifest = json.loads((REPO_ROOT / "web" / "package.json").read_text(encoding="utf-8"))
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        workspace = (REPO_ROOT / "web" / "pnpm-workspace.yaml").read_text(encoding="utf-8")
        wrangler_version = manifest["devDependencies"]["wrangler"]

        assert re.fullmatch(r"\d+\.\d+\.\d+", wrangler_version)
        assert "pnpm --dir web exec wrangler pages deploy dist " in justfile
        assert "  workerd: true" in workspace


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

    def test_every_previewed_flag_exists_in_the_cli(self, cli):
        declared = TestReadmeDocumentsEveryCliFlag._declared_option_strings(cli)

        block = self._scene_block()
        commands = re.findall(r"command: [\"'](agent-dump [^\"']+)[\"']", block)
        assert commands, "至少要有一个终端场景"

        for command in commands:
            for token in shlex.split(command)[1:]:
                if token.startswith("-"):
                    assert token in declared, f"{command!r} 用了 CLI 没有的参数 {token}"

    def test_the_markdown_scene_uses_the_real_default_output_root(self, cli):
        from cli_fixture import IDENTITY

        result = cli.run("rust", f"codex://{IDENTITY}", "--format", "md", "--lang", "en")
        assert result.returncode == 0, result.stderr
        exports = list(cli.root.glob("sessions/codex/*.md"))
        assert len(exports) == 1
        assert "sessions/codex/" in self._scene_block()
        assert "./exports/" not in self._scene_block()

    def test_previewed_uris_use_registered_schemes(self, cli):
        result = cli.run("rust", "--providers", "--lang", "en")
        assert result.returncode == 0, result.stderr
        registered = set(re.findall(r"([a-z][a-z0-9]*)://", result.stdout))
        previewed = set(re.findall(r"([a-z][a-z0-9]*)://", self._scene_block()))
        assert not previewed - registered

    def test_interactive_scene_shows_the_two_stage_selection(self):
        """真实流程是先选 Provider 再选该 Provider 的会话，不是跨 Provider 的单一列表。"""
        catalog = json.loads((REPO_ROOT / "resources/locales/en.json").read_text(encoding="utf-8"))
        agent_prompt = catalog["SELECT_AGENT_PROMPT"]
        sessions_header = catalog["AVAILABLE_SESSIONS"]

        block = self._scene_block()
        assert agent_prompt in block, "缺少选择 Provider 这一步"
        assert sessions_header in block
        assert block.index(agent_prompt) < block.index(sessions_header), "Provider 选择在会话列表之前"

    def test_search_scene_uses_the_real_header_and_labels(self):
        catalog = json.loads((REPO_ROOT / "resources/locales/en.json").read_text(encoding="utf-8"))
        header = catalog["SEARCH_HEADER"].format(days=7, query="auth timeout").strip().lstrip("🔎 ")

        block = self._scene_block()
        assert header in block, f"search header 与 CLI 不一致，实际是: {header!r}"
        assert "ranked by relevance" not in block, "renderer 不打印这一行"
        for label in ("Provider:", "URI:", "Snippet:"):
            assert label in block, f"search 结果缺少真实字段标签 {label}"
