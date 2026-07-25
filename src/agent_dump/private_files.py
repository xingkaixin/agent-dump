"""Permissions for the private files this tool creates under the user's home.

config.toml 早已刻意写成 0600，但从会话数据派生出的东西体量大得多：搜索索引里有
每个会话的每条消息与工具输出，collect 日志里有模型输出片段。它们默认按 umask 创建
（通常是 0755 目录下的 0644 文件），在多用户或共享镜像的机器上等于把用户 AI 会话的
完整可检索副本对本机所有账户开放。
"""

import os
from pathlib import Path

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


def open_private_append(path: Path):
    """Open a file for appending, creating it with owner-only permissions."""
    ensure_private_dir(path.parent)
    # 先用 os.open 带 mode 创建，避免文件在 umask 下先以宽权限存在再被 chmod 收紧
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, PRIVATE_FILE_MODE)
    return os.fdopen(fd, "a", encoding="utf-8")
