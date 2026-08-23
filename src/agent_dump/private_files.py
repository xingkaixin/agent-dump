"""Permissions for the private files this tool creates under the user's home.

config.toml 早已刻意写成 0600，但从会话数据派生出的东西体量大得多：搜索索引里有
每个会话的每条消息与工具输出，collect 日志里有模型输出片段，Export 与 Collect Report
里有完整提示词、源码与工具输出。它们默认按 umask 创建（通常是 0755 目录下的 0644
文件），在多用户或共享镜像的机器上等于把用户 AI 会话的完整副本对本机所有账户开放。
"""

from contextlib import suppress
import os
from pathlib import Path
import shutil
from tempfile import mkstemp
from typing import TextIO

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort chmod; POSIX modes are not meaningful on Windows."""
    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError:
        # 权限本身改不动时（只读挂载、别人拥有的文件）不该让整条命令失败
        return


def ensure_private_dir(path: Path) -> Path:
    """Create a directory tree owner-only, tightening it if it already exists."""
    path.mkdir(parents=True, exist_ok=True)
    _chmod_quietly(path, PRIVATE_DIR_MODE)
    return path


def ensure_private_file(path: Path) -> Path:
    """Create the parent tree owner-only and restrict the file if it exists.

    已存在的文件也会被收紧，否则升级前建出来的宽权限副本会一直留着。
    """
    ensure_private_dir(path.parent)
    if path.exists():
        _chmod_quietly(path, PRIVATE_FILE_MODE)
    return path


def ensure_output_dir(path: Path) -> Path:
    """Create an output directory tree, making only the parts this call creates private.

    与 ensure_private_dir 的区别是刻意的：那个函数管的是本工具自有的目录（缓存、
    日志），可以无条件收紧。导出目录可能是用户自己指定的既有目录，甚至是家目录，
    对它 chmod 就越权了。只有本次调用真正新建出来的层级才设成 0700。
    """
    missing: list[Path] = []
    probe = path
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent

    path.mkdir(parents=True, exist_ok=True)
    for created in missing:
        _chmod_quietly(created, PRIVATE_DIR_MODE)
    return path


def write_private_text(path: Path, text: str) -> Path:
    """Atomically replace a text file with owner-only content."""
    ensure_output_dir(path.parent)
    fd, temporary_name = mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        with suppress(OSError):
            temporary_path.unlink()
        raise
    return path


def copy_private_file(source: Path, destination: Path) -> Path:
    """Atomically copy a file into an owner-only destination."""
    ensure_output_dir(destination.parent)
    fd, temporary_name = mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary_path = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, PRIVATE_FILE_MODE)
        with source.open("rb") as source_handle, os.fdopen(fd, "wb") as destination_handle:
            fd = -1
            shutil.copyfileobj(source_handle, destination_handle)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        with suppress(OSError):
            temporary_path.unlink()
        raise
    return destination


def open_private_append(path: Path) -> TextIO:
    """Open a file for appending, creating it with owner-only permissions."""
    ensure_output_dir(path.parent)
    # mode 只影响新文件；已存在的日志必须通过同一个 fd 收紧，避免路径被替换后 chmod 到别处
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, PRIVATE_FILE_MODE)
    if os.name != "nt":
        with suppress(OSError):
            os.fchmod(fd, PRIVATE_FILE_MODE)
    return os.fdopen(fd, "a", encoding="utf-8")
