"""配置模块测试。"""

from pathlib import Path
from unittest import mock

from agent_dump.config import AIConfig, get_config_path, handle_config_command, load_ai_config, mask_api_key, write_ai_config


class TestConfigPath:
    def test_get_config_path_posix(self, tmp_path):
        path = get_config_path(home=tmp_path / "home", environ={}, is_windows=False)
        assert path == tmp_path / "home" / ".config" / "agent-dump" / "config.toml"

    def test_get_config_path_windows_prefers_appdata(self, tmp_path):
        path = get_config_path(
            home=tmp_path / "home",
            environ={"APPDATA": str(tmp_path / "AppData")},
            is_windows=True,
        )
        assert path == tmp_path / "AppData" / "agent-dump" / "config.toml"


class TestConfigReadWrite:
    def test_write_and_load(self, tmp_path):
        path = tmp_path / "config.toml"
        write_ai_config(
            AIConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4.1-mini",
                api_key="sk-test-123",
            ),
            path,
        )

        config = load_ai_config(path)
        assert config is not None
        assert config.provider == "openai"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.model == "gpt-4.1-mini"
        assert config.api_key == "sk-test-123"

    def test_mask_api_key(self):
        assert mask_api_key("") == ""
        assert mask_api_key("abcdef") == "******"
        assert mask_api_key("sk-123456789") == "sk-******789"


class TestConfigCommand:
    def test_view_existing(self, tmp_path, capsys, monkeypatch):
        path = tmp_path / "config.toml"
        write_ai_config(
            AIConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4.1-mini",
                api_key="sk-test-123",
            ),
            path,
        )
        monkeypatch.setattr("agent_dump.config.get_config_path", lambda **kwargs: path)

        result = handle_config_command("view")
        assert result == 0
        out = capsys.readouterr().out
        assert "当前配置" in out
        assert "sk-*****123" in out

    def test_view_missing_then_create(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        monkeypatch.setattr("agent_dump.config.get_config_path", lambda **kwargs: path)
        monkeypatch.setattr(
            "agent_dump.config.prompt_edit_ai_config",
            lambda existing=None: AIConfig(
                provider="anthropic",
                base_url="https://api.anthropic.com/v1",
                model="claude-3-7-sonnet",
                api_key="ak-test",
            ),
        )

        result = handle_config_command("view", input_fn=lambda _: "y")
        assert result == 0
        assert path.exists()
        saved = load_ai_config(path)
        assert saved is not None
        assert saved.provider == "anthropic"

    def test_edit_cancelled(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        monkeypatch.setattr("agent_dump.config.get_config_path", lambda **kwargs: path)
        monkeypatch.setattr("agent_dump.config.prompt_edit_ai_config", lambda existing=None: None)

        result = handle_config_command("edit")
        assert result == 1
        assert not path.exists()

    def test_invalid_action(self):
        result = handle_config_command("bad-action", input_fn=lambda _: "n")
        assert result == 1

    def test_prompt_edit_simple_mode(self, monkeypatch):
        monkeypatch.setattr("agent_dump.config._is_terminal", lambda: False)
        inputs = iter(["1", "https://api.openai.com/v1", "gpt-4.1-mini", "sk-123", "y"])
        with mock.patch("builtins.input", side_effect=lambda _="": next(inputs)):
            from agent_dump.config import prompt_edit_ai_config

            edited = prompt_edit_ai_config()

        assert edited is not None
        assert edited.provider == "openai"
        assert edited.model == "gpt-4.1-mini"
