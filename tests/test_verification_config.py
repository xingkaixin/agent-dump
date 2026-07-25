"""Guards for the verification configuration itself (AD-135).

这些约束不靠人记，靠测试守住：pytest 只认一个配置文件、tests 在 ruff 范围内、
`just lint` 同时校验 check 与 format。
"""

from pathlib import Path
import sys

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 无 tomllib，与 config.py 采用同一守卫
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_toml(name: str) -> dict:
    return tomllib.loads((REPO_ROOT / name).read_text(encoding="utf-8"))


class TestSinglePytestConfig:
    @pytest.mark.parametrize("shadowing_file", ["pytest.ini", "setup.cfg", "tox.ini"])
    def test_no_file_shadows_the_pyproject_config(self, shadowing_file):
        """pytest 只认一个配置文件，这些文件的优先级都高于 pyproject.toml。

        pytest.ini 曾静默覆盖 [tool.pytest.ini_options] 约五个月，
        testpaths / markers / addopts 全部失效。
        """
        assert not (REPO_ROOT / shadowing_file).exists(), (
            f"{shadowing_file} 会覆盖 pyproject.toml 的 [tool.pytest.ini_options]"
        )

    def test_pytest_config_lives_in_pyproject(self):
        options = _read_toml("pyproject.toml")["tool"]["pytest"]["ini_options"]

        assert options["testpaths"] == ["tests"]
        assert any("slow" in marker for marker in options["markers"])

    def test_coverage_is_not_in_default_addopts(self):
        """否则 `pytest -k one_test` 会打印接近 0% 的报告，读起来像失败。"""
        options = _read_toml("pyproject.toml")["tool"]["pytest"]["ini_options"]

        assert "--cov" not in options.get("addopts", "")

    def test_coverage_floor_is_configured(self):
        assert _read_toml("pyproject.toml")["tool"]["coverage"]["report"]["fail_under"] > 0


class TestRuffCoversTests:
    def test_tests_directory_is_not_excluded(self):
        """排除 tests 会让下面的 per-file-ignores 变成死配置。"""
        excluded = _read_toml("ruff.toml").get("exclude", [])

        assert "tests" not in excluded

    @pytest.mark.parametrize("rule", ["S101", "S108", "SIM117"])
    def test_test_relaxations_are_declared(self, rule):
        ignores = _read_toml("ruff.toml")["lint"]["per-file-ignores"]

        assert rule in ignores["tests/*.py"]
        assert rule in ignores["tests/**/*.py"]


class TestJustLintGatesFormatting:
    def test_lint_recipe_checks_both_check_and_format(self):
        """CI 只跑 just lint；没有 format --check 时格式漂移会一路进主干。"""
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        lint_recipe = justfile.split("lint:", 1)[1].split("\n\n", 1)[0]

        assert "ruff check ." in lint_recipe
        assert "ruff format --check ." in lint_recipe

    def test_cov_recipe_exists(self):
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")

        assert "\ncov:" in justfile
        assert "--cov=src" in justfile


class TestDependencyPinning:
    """AD-143：门禁 CI 与 release 的工具必须固定版本。"""

    def test_type_checkers_are_pinned(self):
        """ty 是 0.0.x；未固定时一个新默认规则就能在代码不变的情况下让发布卡住。"""
        dev_deps = _read_toml("pyproject.toml")["dependency-groups"]["dev"]
        ty_specs = [d for d in dev_deps if d.startswith("ty")]

        assert ty_specs, "ty 应在 dev 依赖里"
        assert all("==" in spec or "~=" in spec for spec in ty_specs), f"ty 必须固定版本（当前 {ty_specs}）"

    def test_packaging_toolchain_stays_pinned(self):
        """AD-114 固定 PyInstaller 是为了二进制可复现，别被无意放开。"""
        packaging = _read_toml("pyproject.toml")["dependency-groups"]["packaging"]

        assert any("pyinstaller==" in spec for spec in packaging)

    def test_prompt_toolkit_is_justified_in_place(self):
        """代码不直接 import 它，保留的理由必须写在旁边（AGENTS.md §1.2）。"""
        content = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        block = content[content.index("dependencies = [") : content.index("[project.urls]")]

        assert "prompt-toolkit" in block
        assert "key_bindings" in block, "保留未直接 import 的依赖需注明必要性"


class TestCiHasNoDeadSteps:
    def test_no_all_extras_flag(self):
        """pyproject 未定义 optional-dependencies，--all-extras 是 no-op 却暗示 extras 存在。"""
        assert "optional-dependencies" not in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for workflow in ("ci.yml", "release.yml"):
            content = (REPO_ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
            assert "--all-extras" not in content, f"{workflow} 仍有 no-op 的 --all-extras"

    def test_no_python_version_removal_step(self):
        """.python-version 既未被跟踪也不存在，那个 rm -f 恒为 no-op。"""
        assert not (REPO_ROOT / ".python-version").exists()
        content = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        assert "rm -f .python-version" not in content
