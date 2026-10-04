"""Guards against documentation drifting from the code (AD-144)."""

import json
from pathlib import Path
import re
import shlex

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


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


class TestWebsiteMatchesTheRealCli:
    GUIDES = REPO_ROOT / "web" / "src" / "pages"
    PROVIDERS = (REPO_ROOT / "web" / "src" / "lib" / "i18n.ts").read_text(encoding="utf-8")

    def test_every_guide_flag_exists_in_the_cli(self, cli):
        declared = TestReadmeDocumentsEveryCliFlag._declared_option_strings(cli)
        commands = []
        for guide in self.GUIDES.rglob("*.md"):
            for block in re.findall(r"```sh\n(.*?)```", guide.read_text(encoding="utf-8"), re.S):
                commands.extend(line for line in block.splitlines() if line.startswith("agent-dump "))
        assert commands
        for command in commands:
            for token in shlex.split(command)[1:]:
                if token.startswith("-"):
                    assert token in declared, f"{command!r} uses unknown option {token}"

    def test_export_guides_use_the_real_output_directory(self, cli):
        from cli_fixture import IDENTITY

        result = cli.run(
            "rust",
            f"codex://{IDENTITY}",
            "--format",
            "markdown",
            "--output",
            "./exports",
            "--lang",
            "en",
        )
        assert result.returncode == 0, result.stderr
        assert len(list(cli.root.glob("exports/codex/*.md"))) == 1
        for guide in self.GUIDES.rglob("export-codex-session.md"):
            assert "./exports/codex/" in guide.read_text(encoding="utf-8")

    def test_guide_uris_use_registered_schemes(self, cli):
        result = cli.run("rust", "--providers", "--json")
        assert result.returncode == 0, result.stderr
        registered = {provider["scheme"] for provider in json.loads(result.stdout)["data"]}
        for guide in self.GUIDES.rglob("*.md"):
            schemes = set(re.findall(r"([a-z][a-z0-9]*)://", guide.read_text(encoding="utf-8")))
            assert not (schemes - {"https"} - registered)

    def test_supported_tools_cover_the_provider_registry(self, cli):
        result = cli.run("rust", "--providers", "--json")
        assert result.returncode == 0, result.stderr
        registered = {provider["scheme"] for provider in json.loads(result.stdout)["data"]}
        start = self.PROVIDERS.index("export const providers")
        block = self.PROVIDERS[start : self.PROVIDERS.index("] as const;", start)]
        listed = set(re.findall(r'example: "([a-z][a-z0-9]*)://', block))
        assert listed == registered
