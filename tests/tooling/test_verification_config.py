"""Keep lock, checksum and release safety boundaries explicit."""

from pathlib import Path
import re

import pytest
import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]


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


class TestPinnedUvInstaller:
    def test_ci_owns_its_uv_pin_and_checksum_verification(self) -> None:
        action = (REPO_ROOT / ".github" / "actions" / "setup-uv" / "action.yml").read_text(encoding="utf-8")

        assert re.search(r'uv_version="\d+\.\d+\.\d+"', action)
        assert re.search(r'uv_sha256="[0-9a-f]{64}"', action)
        assert "pyproject.toml" not in action
        assert "releases/download/$uv_version/" in action
        assert "sha256sum --check" in action
        assert "shasum -a 256 --check" in action


class TestBuildBackendIsReproducible:
    @staticmethod
    def _constraints() -> str:
        return (REPO_ROOT / "packaging" / "build-constraints.txt").read_text(encoding="utf-8")

    @classmethod
    def _constraint_records(cls) -> list[str]:
        logical_lines = cls._constraints().replace("\\\n", " ").splitlines()
        return [line.strip() for line in logical_lines if line.strip() and not line.lstrip().startswith("#")]

    def test_every_build_requirement_is_exact_and_hashed(self):
        records = self._constraint_records()

        assert records
        for record in records:
            requirement = record.split("--hash=", 1)[0]
            assert "==" in requirement, f"构建约束未固定版本: {record}"
            assert "--hash=sha256:" in record, f"构建约束缺少可信 hash: {record}"

    def test_constraint_input_and_generated_maturin_pin_match(self):
        source_pin = (REPO_ROOT / "packaging" / "build-constraints.in").read_text(encoding="utf-8").strip()

        assert source_pin.startswith("maturin==")
        assert any(record.startswith(source_pin) for record in self._constraint_records())

    def test_zig_linker_maturin_matches_the_build_backend(self):
        """Linux 的 zig linker wrapper 调用 packaging 组的 maturin，版本必须与构建后端一致。"""
        source_pin = (REPO_ROOT / "packaging" / "build-constraints.in").read_text(encoding="utf-8").strip()
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        assert source_pin in pyproject["dependency-groups"]["packaging"]

    def test_local_and_release_builds_use_the_same_hash_gate(self):
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        artifacts = (REPO_ROOT / ".github/workflows/build-artifacts.yml").read_text(encoding="utf-8")
        builder = (REPO_ROOT / "packaging/build_release.py").read_text(encoding="utf-8")
        assert "uv run --group packaging python packaging/build_release.py" in justfile
        assert "uv run --group packaging python packaging/build_release.py" in artifacts
        for flag in ("--no-sources", "--build-constraint", "--require-hashes"):
            assert flag in builder
        for workflow in ("ci.yml", "release.yml"):
            content = (REPO_ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
            assert "uses: ./.github/workflows/build-artifacts.yml" in content

    def test_ci_builds_and_smokes_the_constrained_wheel(self):
        artifacts = (REPO_ROOT / ".github/workflows/build-artifacts.yml").read_text(encoding="utf-8")
        assert "packaging/verify_wheel.py --python 3.10" in artifacts
        assert "packaging/verify_wheel.py --python 3.14" in artifacts
        assert "manylinux2014_x86_64@sha256:" in artifacts

    def test_clean_build_does_not_sync_the_project_before_the_hash_gate(self):
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        clean_recipe = justfile.split("\nclean-build:", 1)[1].split("\n\n", 1)[0]

        assert "uv run --no-project python" in clean_recipe


class TestPinnedJustInstaller:
    def test_local_just_installer_pins_and_verifies_the_release(self):
        action = (REPO_ROOT / ".github" / "actions" / "setup-just" / "action.yml").read_text(encoding="utf-8")

        assert re.search(r'JUST_VERSION: "\d+\.\d+\.\d+"', action)
        assert re.search(r'JUST_SHA256: "[0-9a-f]{64}"', action)
        assert "releases/download/$JUST_VERSION/" in action
        assert "sha256sum --check" in action


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


class TestReleasePermissions:
    @staticmethod
    def _release() -> str:
        return (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_release_defaults_to_read_only_contents(self):
        preamble = self._release().split("\njobs:\n", 1)[0]

        assert "permissions:\n  contents: read" in preamble
        assert "permissions:\n  contents: write" not in preamble

    def test_only_publish_job_can_write_contents(self):
        release = self._release()
        publish = release.split("\n  publish:\n", 1)[1].split("\n  smoke-npm:\n", 1)[0]

        assert "permissions:\n      id-token: write\n      contents: write" in publish
        assert release.count("contents: write") == 1


class TestReleaseRetries:
    @staticmethod
    def _release() -> str:
        return (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_npm_publish_checks_existing_tarball_integrity(self):
        release = self._release()
        publish = release.split("\n      - name: Publish npm packages\n", 1)[1].split(
            "\n      - name: Publish to PyPI\n", 1
        )[0]

        assert "node npm/scripts/restore-published-binaries.mjs" in release
        assert "npm --prefix npm run smoke -- --all-platforms --keep-pack" in release
        assert "node npm/scripts/publish-if-needed.mjs --release-dir ./npm/.pack" in publish
        assert ".tgz" not in publish
        assert "./npm/packages/" not in publish

    def test_same_tag_release_runs_are_serialized_without_cancellation(self):
        preamble = self._release().split("\njobs:\n", 1)[0]
        concurrency = preamble.split("\nconcurrency:\n", 1)[1].split("\nenv:\n", 1)[0]

        assert "github.workflow" in concurrency
        assert "github.ref" in concurrency
        assert "cancel-in-progress: false" in concurrency

    def test_release_assets_use_the_effective_npm_binaries(self):
        release = self._release()
        stage_release = release.split("\n      - name: Stage GitHub release assets\n", 1)[1].split(
            "\n      - name: Verify existing GitHub release assets\n", 1
        )[0]

        assert "node npm/scripts/stage-release-assets.mjs dist/release" in stage_release
        assert "npm/packages/cli-" not in stage_release
        assert "dist/native/" not in stage_release

    def test_pypi_publish_checks_existing_file_hashes(self):
        assert "uv publish --check-url https://pypi.org/simple/" in self._release()

    def test_github_release_preserves_and_verifies_existing_assets(self):
        release = self._release()

        assert "packaging/verify_release_assets.py" in release
        assert "dist/release/*" in release
        assert "overwrite_files: false" in release
        assert "fail_on_unmatched_files: true" in release


class TestVerificationConsumesTheCommittedLock:
    """AD-174：uv sync/run 默认会重新锁定，验证过程绝不能修改 uv.lock。

    临时 checkout 里的静默重锁不会出现在 PR diff，评审看到的解析结果与实际安装、
    实际发布的就不是一回事了。
    """

    @staticmethod
    def _workflow(name: str) -> str:
        return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    @pytest.mark.parametrize("workflow", ["ci.yml", "release.yml", "build-artifacts.yml"])
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

    @pytest.mark.parametrize("workflow", ["ci.yml", "release.yml", "build-artifacts.yml"])
    def test_uv_locked_is_set_for_the_whole_workflow(self, workflow):
        """--locked 只管 uv sync；后续的 uv run 需要 UV_LOCKED 才受同一约束。"""
        content = self._workflow(workflow)

        assert 'UV_LOCKED: "1"' in content, f"{workflow} 未设置 UV_LOCKED"
