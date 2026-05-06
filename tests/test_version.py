"""
测试版本元数据
"""

from importlib.metadata import version
from pathlib import Path

import pytest

import agent_dump
from agent_dump import __version__
from agent_dump.__about__ import __version__ as about_version


def _is_editable_import() -> bool:
    """判断当前是否从仓库源码目录导入包。"""
    package_file = Path(agent_dump.__file__).resolve()
    return "site-packages" not in package_file.parts


def test_runtime_version_re_exports_about_version() -> None:
    """测试包顶层版本号与单一版本源一致"""
    assert __version__ == about_version


def test_top_level_public_api_matches_declared_exports() -> None:
    """测试顶层公开 API 声明保持可导入。"""
    expected_exports = {
        "__version__",
        "AgentScanner",
        "BaseAgent",
        "Session",
        "OpenCodeAgent",
        "CodexAgent",
        "KimiAgent",
        "ClaudeCodeAgent",
        "CursorAgent",
    }

    assert set(agent_dump.__all__) == expected_exports
    for name in expected_exports:
        assert hasattr(agent_dump, name)


def test_installed_metadata_version_matches_runtime_version() -> None:
    """测试安装元数据版本与运行时版本一致"""
    if _is_editable_import():
        pytest.skip("editable/source import detected: installed metadata may be stale")

    assert version("agent-dump") == __version__
