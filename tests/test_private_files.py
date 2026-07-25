"""Tests for private_files.py 与派生数据文件的权限约束。"""

import os
from pathlib import Path
import stat

import pytest

from agent_dump.private_files import (
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
    ensure_private_dir,
    ensure_private_file,
    open_private_append,
)

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位在 Windows 上无意义")


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
class TestEnsurePrivateDir:
    def test_creates_owner_only_directory(self, tmp_path):
        target = tmp_path / "a" / "b"

        ensure_private_dir(target)

        assert target.is_dir()
        assert mode_of(target) == PRIVATE_DIR_MODE

    def test_tightens_an_existing_world_readable_directory(self, tmp_path):
        target = tmp_path / "loose"
        target.mkdir(mode=0o755)

        ensure_private_dir(target)

        assert mode_of(target) == PRIVATE_DIR_MODE


@posix_only
class TestEnsurePrivateFile:
    def test_creates_parent_and_tightens_existing_file(self, tmp_path):
        target = tmp_path / "nested" / "data.db"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        target.chmod(0o644)

        ensure_private_file(target)

        assert mode_of(target) == PRIVATE_FILE_MODE
        assert mode_of(target.parent) == PRIVATE_DIR_MODE

    def test_missing_file_is_not_an_error(self, tmp_path):
        target = tmp_path / "nested" / "absent.db"

        ensure_private_file(target)

        assert target.parent.is_dir()
        assert not target.exists()


@posix_only
class TestOpenPrivateAppend:
    def test_new_file_is_never_world_readable(self, tmp_path):
        target = tmp_path / "logs" / "collect.log"

        with open_private_append(target) as handle:
            handle.write("first\n")

        assert mode_of(target) == PRIVATE_FILE_MODE
        assert mode_of(target.parent) == PRIVATE_DIR_MODE

    def test_appends_rather_than_truncates(self, tmp_path):
        target = tmp_path / "logs" / "collect.log"

        with open_private_append(target) as handle:
            handle.write("first\n")
        with open_private_append(target) as handle:
            handle.write("second\n")

        assert target.read_text(encoding="utf-8") == "first\nsecond\n"


@posix_only
class TestDerivedDataFilePermissions:
    """AD-129：索引与 collect 日志含全部会话内容，权限必须与 config.toml 对齐。"""

    def test_search_index_database_is_owner_only(self, tmp_path):
        from agent_dump.search_index import SearchIndex

        db_path = tmp_path / "cache" / "search-index.db"
        index = SearchIndex(db_path)
        index.ensure_initialized()

        assert db_path.exists(), "ensure_initialized 应已建库"
        assert mode_of(db_path) == PRIVATE_FILE_MODE
        assert mode_of(db_path.parent) == PRIVATE_DIR_MODE

    def test_collect_log_is_owner_only(self, tmp_path):
        from agent_dump.collect_models import CollectLogger

        log_path = tmp_path / "logs" / "collect.log"
        CollectLogger(enabled=True, path=log_path, run_id="r1").log("started", detail="x")

        assert log_path.exists()
        assert mode_of(log_path) == PRIVATE_FILE_MODE
        assert mode_of(log_path.parent) == PRIVATE_DIR_MODE

    def test_config_file_shares_the_same_mode_constant(self):
        from agent_dump.config import PRIVATE_CONFIG_MODE

        assert PRIVATE_CONFIG_MODE == PRIVATE_FILE_MODE
