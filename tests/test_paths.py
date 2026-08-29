"""
测试路径解析模块。
"""

from pathlib import Path

import pytest

from agent_dump.agent_registry import get_supported_agent_locations
from agent_dump.agents.cursor import CursorAgent
from agent_dump.paths import (
    SearchRoot,
    first_existing_search_root,
    render_search_roots,
    resolve_data_home,
    resolve_env_path,
)


class TestPathResolution:
    """测试通用路径解析原语。"""

    def test_resolve_env_path_prefers_non_empty_value(self, tmp_path: Path) -> None:
        resolved = resolve_env_path(
            "AGENT_HOME",
            tmp_path / "default",
            environ={"AGENT_HOME": str(tmp_path / "configured")},
        )

        assert resolved == tmp_path / "configured"

    def test_resolve_env_path_uses_default_for_empty_value(self, tmp_path: Path) -> None:
        default = tmp_path / "default"

        assert resolve_env_path("AGENT_HOME", default, environ={"AGENT_HOME": ""}) == default

    def test_resolve_data_home_prefers_xdg(self, tmp_path: Path) -> None:
        resolved = resolve_data_home(
            home=tmp_path / "home",
            environ={"XDG_DATA_HOME": str(tmp_path / "xdg-data")},
            is_windows=False,
        )

        assert resolved == tmp_path / "xdg-data"

    def test_resolve_data_home_uses_local_app_data_on_windows(self, tmp_path: Path) -> None:
        resolved = resolve_data_home(
            home=tmp_path / "home",
            environ={"LOCALAPPDATA": str(tmp_path / "LocalAppData")},
            is_windows=True,
        )

        assert resolved == tmp_path / "LocalAppData"

    def test_resolve_data_home_uses_app_data_when_local_app_data_missing(self, tmp_path: Path) -> None:
        resolved = resolve_data_home(
            home=tmp_path / "home",
            environ={"APPDATA": str(tmp_path / "AppData")},
            is_windows=True,
        )

        assert resolved == tmp_path / "AppData"

    def test_resolve_data_home_uses_home_default(self, tmp_path: Path) -> None:
        resolved = resolve_data_home(
            home=tmp_path / "home",
            environ={},
            is_windows=False,
        )

        assert resolved == tmp_path / "home" / ".local" / "share"


class TestSearchRoots:
    def test_first_existing_search_root_prefers_first_existing_candidate(self, tmp_path):
        missing = SearchRoot("env", tmp_path / "missing")
        existing = SearchRoot("fallback", tmp_path / "data")
        existing.path.mkdir()

        assert first_existing_search_root(missing, existing) == existing.path

    def test_render_search_roots_preserves_labels_and_order(self, tmp_path):
        roots = (
            SearchRoot("CODEX_HOME/sessions", tmp_path / "codex"),
            SearchRoot("local development fallback", tmp_path / "data/codex"),
        )

        assert render_search_roots(*roots) == (
            f"CODEX_HOME/sessions: {tmp_path / 'codex'}",
            f"local development fallback: {tmp_path / 'data/codex'}",
        )

    def test_supported_locations_use_provider_search_roots(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        root = SearchRoot("platform-specific Cursor database", tmp_path / "state.vscdb")
        monkeypatch.setattr(CursorAgent, "get_search_roots", lambda _self: (root,))

        locations = get_supported_agent_locations()

        assert f"  - Cursor: {root.render()}" in locations
