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


def _read_json(name: str) -> dict:
    import json

    return json.loads((REPO_ROOT / name).read_text(encoding="utf-8"))


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


class TestBuildBackendIsReproducible:
    @staticmethod
    def _constraints() -> str:
        return (REPO_ROOT / "packaging" / "build-constraints.txt").read_text(encoding="utf-8")

    @classmethod
    def _constraint_records(cls) -> list[str]:
        logical_lines = cls._constraints().replace("\\\n", " ").splitlines()
        return [line.strip() for line in logical_lines if line.strip() and not line.lstrip().startswith("#")]

    def test_build_backend_requirement_has_a_version_policy(self):
        requirements = _read_toml("pyproject.toml")["build-system"]["requires"]
        hatchling = [requirement for requirement in requirements if requirement.startswith("hatchling")]

        assert len(hatchling) == 1
        assert hatchling[0] != "hatchling"
        assert ">=" in hatchling[0]
        assert "<2" in hatchling[0]

    def test_every_build_requirement_is_exact_and_hashed(self):
        records = self._constraint_records()

        assert records
        for record in records:
            requirement = record.split("--hash=", 1)[0]
            assert "==" in requirement, f"构建约束未固定版本: {record}"
            assert "--hash=sha256:" in record, f"构建约束缺少可信 hash: {record}"

    def test_constraint_input_and_generated_hatchling_pin_match(self):
        source_pin = (REPO_ROOT / "packaging" / "build-constraints.in").read_text(encoding="utf-8").strip()

        assert source_pin.startswith("hatchling==")
        assert any(record.startswith(source_pin) for record in self._constraint_records())

    def test_local_and_release_builds_use_the_same_hash_gate(self):
        expected = "uv build --no-sources --build-constraint packaging/build-constraints.txt --require-hashes"
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        release = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

        assert expected in justfile
        assert expected in release

    def test_ci_builds_and_smokes_the_constrained_wheel(self):
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        quality = ci.split("\n  quality:\n", 1)[1].split("\n  python-tests:\n", 1)[0]

        assert "run: just build" in quality
        assert "run: just verify-wheel" in quality

    def test_constraint_refresh_has_a_dependabot_path(self):
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        dependabot = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

        assert "update-build-constraints:" in justfile
        assert "uv pip compile packaging/build-constraints.in" in justfile
        assert "package-ecosystem: pip" in dependabot
        assert "directory: /packaging" in dependabot

    def test_clean_build_does_not_sync_the_project_before_the_hash_gate(self):
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        clean_recipe = justfile.split("\nclean-build:", 1)[1].split("\n\n", 1)[0]

        assert "uv run --no-project python" in clean_recipe


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


class TestCiCancelsSupersededRuns:
    @staticmethod
    def _workflow_preamble(name: str) -> str:
        content = (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        return content.split("\njobs:\n", 1)[0]

    def test_ci_cancels_only_an_older_run_with_the_same_identity(self):
        preamble = self._workflow_preamble("ci.yml")
        concurrency = preamble.split("\nconcurrency:\n", 1)[1].split("\nenv:\n", 1)[0]

        assert "github.workflow" in concurrency
        assert "github.event_name" in concurrency
        assert "github.event.pull_request.number || github.ref" in concurrency
        assert "cancel-in-progress: true" in concurrency

    def test_release_does_not_share_the_ci_cancellation_group(self):
        release_preamble = self._workflow_preamble("release.yml")

        assert "github.event.pull_request.number || github.ref" not in release_preamble


class TestVerificationConsumesTheCommittedLock:
    """AD-174：uv sync/run 默认会重新锁定，验证过程绝不能修改 uv.lock。

    临时 checkout 里的静默重锁不会出现在 PR diff，评审看到的解析结果与实际安装、
    实际发布的就不是一回事了。
    """

    @staticmethod
    def _workflow(name: str) -> str:
        return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    @pytest.mark.parametrize("workflow", ["ci.yml", "release.yml"])
    def test_every_uv_sync_is_locked(self, workflow):
        content = self._workflow(workflow)
        sync_lines = [
            stripped
            for line in content.splitlines()
            if "uv sync" in (stripped := line.strip()) and not stripped.startswith("#")
        ]

        assert sync_lines, f"{workflow} 应当有 uv sync 步骤"
        for line in sync_lines:
            assert "--locked" in line, f"{workflow} 的 `{line}` 会在需要时静默重锁"

    @pytest.mark.parametrize("workflow", ["ci.yml", "release.yml"])
    def test_uv_locked_is_set_for_the_whole_workflow(self, workflow):
        """--locked 只管 uv sync；后续的 uv run 需要 UV_LOCKED 才受同一约束。"""
        content = self._workflow(workflow)

        assert 'UV_LOCKED: "1"' in content, f"{workflow} 未设置 UV_LOCKED"

    def test_isok_checks_the_lock_before_anything_else(self):
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        isok_line = next(line for line in justfile.splitlines() if line.startswith("isok:"))

        assert "lock-check" in isok_line, "本地主验证必须先确认 lock 未漂移"
        assert isok_line.index("lock-check") < isok_line.index("lint")
        assert "uv lock --check" in justfile

    def test_dependency_upgrades_stay_out_of_verification(self):
        """升级依赖是显式动作；验证 recipe 里出现 --upgrade 就等于每次验证都在改锁。"""
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        verification_recipes = ("lock-check:", "lint:", "check:", "test:", "isok:")

        for recipe in verification_recipes:
            if recipe not in justfile:
                continue
            body = justfile.split(recipe, 1)[1].split("\n\n", 1)[0]
            assert "--upgrade" not in body, f"{recipe} 不应在验证过程中升级依赖"


class TestWebIsInTheMainGate:
    """AD-173：Web 有 check/build 却不在门禁里，toolchain 漂移会一路合并进主干。"""

    @staticmethod
    def _ci() -> str:
        return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    @staticmethod
    def _justfile() -> str:
        return (REPO_ROOT / "justfile").read_text(encoding="utf-8")

    def test_ci_runs_the_web_check_and_build(self):
        content = self._ci()

        assert "pnpm --dir web check" in content
        assert "pnpm --dir web build" in content

    def test_web_installs_from_the_committed_lockfile(self):
        """CI 的事实必须来自已提交的 lock，不是解析出的新版本。"""
        assert "pnpm --dir web install --frozen-lockfile" in self._ci()

    def test_web_job_is_not_inside_the_python_matrix(self):
        """否则五个 Python leg 会各装一遍 Web 依赖。"""
        content = self._ci()
        web_job = content.split("\n  web:", 1)[1].split("\n  ", 1)[0]

        assert "matrix.python-version" not in web_job
        assert "\n  web:" in content, "Web 必须是独立 job"

    def test_isok_has_a_matching_local_entry(self):
        justfile = self._justfile()
        isok_body = justfile.split("\nisok:", 1)[1].split("\n\n", 1)[0]

        assert "\ncheck-web:" in justfile
        assert "check-web" in isok_body, "本地主验证要有与 CI 相同的入口"

    def test_local_web_entry_runs_the_same_commands_as_ci(self):
        recipe = self._justfile().split("\ncheck-web:", 1)[1].split("\n\n", 1)[0]

        for command in ("install --frozen-lockfile", "check", "build"):
            assert command in recipe, f"check-web 缺少 {command}"

    def test_pnpm_version_comes_from_the_package_manager_field(self):
        """workflow 里再硬编码一遍 pnpm 版本，就会和 packageManager 各说各话。"""
        content = self._ci()

        assert "package_json_file: web/package.json" in content
        web_package_json = _read_json("web/package.json")
        assert web_package_json["packageManager"].startswith("pnpm@")


class TestCiDoesNotRepeatVersionIndependentWork:
    """AD-175：lint/typecheck 的结论不随运行时 Python 变化，跑五遍只是重复付钱。"""

    @staticmethod
    def _ci() -> str:
        return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    @classmethod
    def _job(cls, name: str) -> str:
        """取出一个 job 的正文。job 是 workflow 里唯一的两空格缩进顶层 key。"""
        content = cls._ci()
        marker = f"\n  {name}:\n"
        assert marker in content, f"ci.yml 缺少 job {name}"
        body = content.split(marker, 1)[1]
        for line in body.splitlines(keepends=True):
            if line.strip() and not line.startswith("    ") and not line.startswith("\t"):
                return body[: body.index(line)]
        return body

    @classmethod
    def _job_names(cls) -> list[str]:
        return [
            line.strip().rstrip(":")
            for line in cls._ci().split("\njobs:\n", 1)[1].splitlines()
            if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":")
        ]

    def test_python_tests_still_cover_every_supported_version(self):
        job = self._job("python-tests")

        for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
            assert f'"{version}"' in job, f"Python {version} 不在测试矩阵里"

    def test_lint_and_typecheck_run_exactly_once(self):
        quality = self._job("quality")
        python_tests = self._job("python-tests")

        assert "run: just lint" in quality
        assert "run: just check" in quality
        assert "matrix:" not in quality, "质量检查不该跟着 matrix 展开"
        assert "run: just lint" not in python_tests, "lint 不该在每个 Python leg 重复"
        assert "run: just check" not in python_tests, "typecheck 不该在每个 Python leg 重复"

    def test_the_coverage_leg_does_not_also_run_a_plain_test(self):
        """just cov 跑的就是完整测试集，再跑一次 just test 是同一批用例跑两遍。"""
        job = self._job("python-tests")

        assert "!= env.COVERAGE_PYTHON_VERSION" in job
        assert "== env.COVERAGE_PYTHON_VERSION" in job
        assert job.count("run: just test") == 1
        assert job.count("run: just cov") == 1

    def test_npm_and_web_are_their_own_jobs(self):
        assert set(self._job_names()) == {"quality", "python-tests", "web", "npm-wrapper"}
        assert "matrix:" not in self._job("web"), "Web 只需构建一次"
        assert '"22"' in self._job("npm-wrapper")
        assert '"24"' in self._job("npm-wrapper")

    def test_no_job_sets_up_a_runtime_it_does_not_use(self):
        """把不同 runtime 的环境事实混进一个 job，失败归因就不清楚了。"""
        assert "setup-node" not in self._job("python-tests")
        assert "setup-uv" not in self._job("npm-wrapper")
        assert "setup-uv" not in self._job("web")
