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
