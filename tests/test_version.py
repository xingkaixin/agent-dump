"""
测试版本元数据
"""

from importlib.metadata import version

from agent_dump import __version__
from agent_dump.__about__ import __version__ as about_version


def test_runtime_version_re_exports_about_version() -> None:
    """测试包顶层版本号与单一版本源一致"""
    assert __version__ == about_version


def test_installed_metadata_version_matches_runtime_version() -> None:
    """测试安装元数据版本与运行时版本一致"""
    assert version("agent-dump") == __version__
