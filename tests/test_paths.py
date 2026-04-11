"""
测试路径解析模块。
"""

from pathlib import Path

from agent_dump.paths import ProviderRoots, SearchRoot, first_existing_search_root, render_search_roots


class TestProviderRoots:
    """测试 ProviderRoots。"""

    def test_prefers_official_env_roots(self, tmp_path):
        environ = {
            "CODEX_HOME": str(tmp_path / "codex-home"),
            "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-home"),
            "KIMI_SHARE_DIR": str(tmp_path / "kimi-home"),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        }

        roots = ProviderRoots.from_env_or_home(
            home=tmp_path / "home",
            environ=environ,
            is_windows=False,
        )

        assert roots.codex_root == tmp_path / "codex-home"
        assert roots.claude_root == tmp_path / "claude-home"
        assert roots.kimi_root == tmp_path / "kimi-home"
        assert roots.opencode_root == tmp_path / "xdg-data" / "opencode"

    def test_ignores_empty_env_values(self, tmp_path):
        roots = ProviderRoots.from_env_or_home(
            home=tmp_path / "home",
            environ={
                "CODEX_HOME": "",
                "CLAUDE_CONFIG_DIR": "",
                "KIMI_SHARE_DIR": "",
                "XDG_DATA_HOME": "",
            },
            is_windows=False,
        )

        assert roots.codex_root == tmp_path / "home" / ".codex"
        assert roots.claude_root == tmp_path / "home" / ".claude"
        assert roots.kimi_root == tmp_path / "home" / ".kimi"
        assert roots.opencode_root == tmp_path / "home" / ".local" / "share" / "opencode"

    def test_uses_local_app_data_on_windows(self, tmp_path):
        roots = ProviderRoots.from_env_or_home(
            home=tmp_path / "home",
            environ={"LOCALAPPDATA": str(tmp_path / "LocalAppData")},
            is_windows=True,
        )

        assert roots.opencode_root == Path(tmp_path / "LocalAppData" / "opencode")

    def test_uses_app_data_when_local_app_data_missing(self, tmp_path):
        roots = ProviderRoots.from_env_or_home(
            home=tmp_path / "home",
            environ={"APPDATA": str(tmp_path / "AppData")},
            is_windows=True,
        )

        assert roots.opencode_root == Path(tmp_path / "AppData" / "opencode")

    def test_uses_home_defaults_without_env(self, tmp_path):
        roots = ProviderRoots.from_env_or_home(
            home=tmp_path / "home",
            environ={},
            is_windows=False,
        )

        assert roots.codex_root == tmp_path / "home" / ".codex"
        assert roots.claude_root == tmp_path / "home" / ".claude"
        assert roots.kimi_root == tmp_path / "home" / ".kimi"
        assert roots.opencode_root == tmp_path / "home" / ".local" / "share" / "opencode"


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
