"""Tests for private_files.py 与派生数据文件的权限约束。"""

from datetime import date, datetime, timezone
import os
from pathlib import Path
import shutil
import stat

import pytest

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.collect_output import write_collect_markdown
from agent_dump.private_files import (
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
    copy_private_file,
    ensure_output_dir,
    ensure_private_dir,
    ensure_private_file,
    open_private_append,
    write_private_text,
)
from agent_dump.rendering import export_session_markdown

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

    def test_preserves_existing_parent_and_tightens_existing_file(self, tmp_path):
        parent = tmp_path / "user-logs"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        target = parent / "collect.log"
        target.write_text("old\n", encoding="utf-8")
        target.chmod(0o644)

        with open_private_append(target) as handle:
            handle.write("new\n")

        assert mode_of(parent) == 0o755
        assert mode_of(target) == PRIVATE_FILE_MODE
        assert target.read_text(encoding="utf-8") == "old\nnew\n"


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
        from agent_dump.collect_logging import CollectLogger

        log_path = tmp_path / "logs" / "collect.log"
        CollectLogger(enabled=True, path=log_path, run_id="r1").log("started", detail="x")

        assert log_path.exists()
        assert mode_of(log_path) == PRIVATE_FILE_MODE
        assert mode_of(log_path.parent) == PRIVATE_DIR_MODE


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestCopyPrivateFile:
    def test_failed_copy_preserves_existing_target(self, tmp_path, monkeypatch):
        source = tmp_path / "source.jsonl"
        source.write_text("new complete export", encoding="utf-8")
        target = tmp_path / "copy.jsonl"
        target.write_text("old complete export", encoding="utf-8")

        def fail_mid_copy(source_handle, destination_handle):
            destination_handle.write(source_handle.read(3))
            raise OSError("copy failed")

        monkeypatch.setattr("agent_dump.private_files.shutil.copyfileobj", fail_mid_copy)

        with pytest.raises(OSError, match="copy failed"):
            copy_private_file(source, target)

        assert target.read_text(encoding="utf-8") == "old complete export"
        assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []

    @pytest.mark.skipif(os.name == "nt", reason="symbolic link behavior differs on Windows")
    def test_copy_replaces_destination_symlink_without_touching_its_target(self, tmp_path):
        source = tmp_path / "source.jsonl"
        source.write_text("session export", encoding="utf-8")
        linked_target = tmp_path / "unrelated.txt"
        linked_target.write_text("keep me", encoding="utf-8")
        destination = tmp_path / "copy.jsonl"
        destination.symlink_to(linked_target)

        copy_private_file(source, destination)

        assert not destination.is_symlink()
        assert destination.read_text(encoding="utf-8") == "session export"
        assert linked_target.read_text(encoding="utf-8") == "keep me"


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes are not meaningful on Windows")
class TestExportsAndReportsArePrivate:
    """AD-166：Export 与 Collect Report 含完整提示词、源码与工具输出。"""

    @pytest.fixture(autouse=True)
    def _permissive_umask(self):
        previous = os.umask(0o022)
        yield
        os.umask(previous)

    class _DummyAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__("dummy", "Dummy")

        def scan(self):
            return []

        def is_available(self) -> bool:
            return True

        def get_sessions(self, days: int | None = 7):
            return []

        def get_session_data(self, session) -> dict:
            return {"id": session.id, "messages": []}

    @staticmethod
    def _session(tmp_path: Path) -> Session:
        source = tmp_path / "source.jsonl"
        source.write_text('{"a": 1}\n', encoding="utf-8")
        source.chmod(0o644)
        now = datetime.now(timezone.utc)
        return Session(id="s1", title="T", created_at=now, updated_at=now, source_path=source, metadata={})

    def test_json_export_file_and_new_dir_are_owner_only(self, tmp_path):
        output_dir = tmp_path / "sessions" / "dummy"

        exported = self._DummyAgent().export_session(self._session(tmp_path), output_dir)

        assert _mode(exported) == PRIVATE_FILE_MODE
        assert _mode(output_dir) == PRIVATE_DIR_MODE

    def test_raw_export_tightens_the_copy_without_touching_the_source(self, tmp_path):
        session = self._session(tmp_path)

        exported = self._DummyAgent().export_raw_session(session, tmp_path / "raw")

        assert _mode(exported) == PRIVATE_FILE_MODE
        assert _mode(session.source_path) == 0o644, "Provider Session Source 是只读数据，绝不修改"

    def test_markdown_export_is_owner_only(self, tmp_path):
        output_dir = tmp_path / "md"

        exported = export_session_markdown("dummy://s1", {"id": "s1", "messages": []}, "s1", output_dir)

        assert _mode(exported) == PRIVATE_FILE_MODE
        assert _mode(output_dir) == PRIVATE_DIR_MODE

    def test_collect_report_is_owner_only(self, tmp_path):
        output_dir = tmp_path / "collect"

        report = write_collect_markdown(
            "# report",
            since_date=date(2026, 1, 1),
            until_date=date(2026, 1, 2),
            output_dir=output_dir,
        )

        assert _mode(report) == PRIVATE_FILE_MODE
        assert _mode(output_dir) == PRIVATE_DIR_MODE

    def test_existing_output_dir_keeps_its_mode(self, tmp_path):
        """用户显式指定的既有目录不该被本工具 chmod。"""
        output_dir = tmp_path / "user-dir"
        output_dir.mkdir()
        # 刻意造一个宽权限的既有目录：断言的正是本工具不会去改它
        os.chmod(output_dir, 0o755)  # noqa: S103

        exported = self._DummyAgent().export_session(self._session(tmp_path), output_dir)

        assert _mode(output_dir) == 0o755
        assert _mode(exported) == PRIVATE_FILE_MODE, "既有目录里的新文件仍必须私有"

    def test_only_newly_created_levels_are_tightened(self, tmp_path):
        existing = tmp_path / "existing"
        existing.mkdir()
        os.chmod(existing, 0o755)  # noqa: S103

        ensure_output_dir(existing / "a" / "b")

        assert _mode(existing) == 0o755, "既有祖先目录不得被收紧"
        assert _mode(existing / "a") == PRIVATE_DIR_MODE
        assert _mode(existing / "a" / "b") == PRIVATE_DIR_MODE

    def test_existing_world_readable_target_is_tightened_on_overwrite(self, tmp_path):
        """升级前建出来的宽权限副本，覆盖时要收紧。"""
        target = tmp_path / "old.md"
        target.write_text("old", encoding="utf-8")
        os.chmod(target, 0o644)

        write_private_text(target, "new")

        assert _mode(target) == PRIVATE_FILE_MODE
        assert target.read_text(encoding="utf-8") == "new"

    def test_failed_text_write_preserves_existing_target(self, tmp_path, monkeypatch):
        target = tmp_path / "report.md"
        target.write_text("old complete report", encoding="utf-8")

        def fail_fdopen(*_args, **_kwargs):
            raise OSError("write failed")

        monkeypatch.setattr("agent_dump.private_files.os.fdopen", fail_fdopen)

        with pytest.raises(OSError, match="write failed"):
            write_private_text(target, "new report")

        assert target.read_text(encoding="utf-8") == "old complete report"
        assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []

    def test_copy_private_file_tightens_a_world_readable_source(self, tmp_path):
        source = tmp_path / "src.jsonl"
        source.write_text("data", encoding="utf-8")
        os.chmod(source, 0o644)

        copied = copy_private_file(source, tmp_path / "out" / "copy.jsonl")

        assert _mode(copied) == PRIVATE_FILE_MODE
        assert _mode(source) == 0o644

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
    def test_copy_private_file_is_private_before_writing_content(self, tmp_path, monkeypatch):
        source = tmp_path / "src.jsonl"
        source.write_text("sensitive", encoding="utf-8")
        os.chmod(source, 0o644)
        destination = tmp_path / "existing" / "copy.jsonl"
        destination.parent.mkdir()
        destination.write_text("old", encoding="utf-8")
        os.chmod(destination, 0o644)
        modes_during_copy: list[int] = []
        original_copyfileobj = shutil.copyfileobj

        def record_destination_mode(source_handle, destination_handle):
            modes_during_copy.append(os.fstat(destination_handle.fileno()).st_mode & 0o777)
            original_copyfileobj(source_handle, destination_handle)

        monkeypatch.setattr("agent_dump.private_files.shutil.copyfileobj", record_destination_mode)

        copy_private_file(source, destination)

        assert modes_during_copy == [PRIVATE_FILE_MODE]
        assert destination.read_text(encoding="utf-8") == "sensitive"
