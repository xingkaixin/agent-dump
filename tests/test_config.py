"""配置模块测试。"""

from pathlib import Path
from unittest import mock

from agent_dump.config import (
    AIConfig,
    CollectConfig,
    get_config_path,
    handle_config_command,
    load_ai_config,
    load_collect_config,
    load_logging_config,
    load_shortcuts_config,
    LoggingConfig,
    mask_api_key,
    ShortcutConfig,
    write_ai_config,
)


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
        assert load_collect_config(path) == CollectConfig()

    def test_load_collect_config_reads_summary_concurrency(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[ai]\n"
                'provider = "openai"\n'
                'base_url = "https://api.openai.com/v1"\n'
                'model = "gpt-4.1-mini"\n'
                'api_key = "sk-test-123"\n'
                "\n[collect]\n"
                "summary_concurrency = 8\n"
                "summary_timeout_seconds = 120\n"
            ),
            encoding="utf-8",
        )

        assert load_collect_config(path) == CollectConfig(summary_concurrency=8, summary_timeout_seconds=120)

    def test_load_collect_config_reads_agent_deny_paths(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[collect]\n"
                "summary_concurrency = 8\n"
                "\n[agent.claudecode]\n"
                'deny = [\n  "/repo/a",\n  "/repo/b/sub"\n]\n'
            ),
            encoding="utf-8",
        )

        assert load_collect_config(path) == CollectConfig(
            summary_concurrency=8,
            agent_denies={"claudecode": ("/repo/a", "/repo/b/sub")},
        )

    def test_load_collect_config_falls_back_for_invalid_value(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[ai]\n"
                'provider = "openai"\n'
                'base_url = "https://api.openai.com/v1"\n'
                'model = "gpt-4.1-mini"\n'
                'api_key = "sk-test-123"\n'
                "\n[collect]\n"
                'summary_concurrency = "bad"\n'
            ),
            encoding="utf-8",
        )

        assert load_collect_config(path) == CollectConfig()

    def test_load_collect_config_ignores_invalid_agent_deny(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[collect]\n"
                "summary_concurrency = 2\n"
                "\n[agent.claudecode]\n"
                "deny = bad\n"
                "\n[agent.codex]\n"
                "deny = []\n"
            ),
            encoding="utf-8",
        )

        assert load_collect_config(path) == CollectConfig(summary_concurrency=2)

    def test_load_logging_config_reads_values(self, tmp_path):
        path = tmp_path / "config.toml"
        log_path = tmp_path / "logs" / "collect.jsonl"
        path.write_text(
            (
                "[logging]\n"
                "enabled = false\n"
                f'path = "{log_path}"\n'
            ),
            encoding="utf-8",
        )

        assert load_logging_config(path) == LoggingConfig(enabled=False, path=log_path)

    def test_load_logging_config_defaults_to_config_dir(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        monkeypatch.setattr("agent_dump.config.get_config_path", lambda **kwargs: path)

        assert load_logging_config(path) == LoggingConfig(enabled=True, path=tmp_path / "logs" / "collect.log")

    def test_load_shortcuts_config_reads_shortcuts(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[shortcut.ob]\n"
                'params = ["date"]\n'
                'args = ["--collect", "--since", "{date}", "--until", "{date}"]\n'
            ),
            encoding="utf-8",
        )

        assert load_shortcuts_config(path) == {
            "ob": ShortcutConfig(
                params=("date",),
                args=("--collect", "--since", "{date}", "--until", "{date}"),
            )
        }

    def test_load_shortcuts_config_accepts_trailing_comma_in_multiline_args(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[shortcut.ob]\n"
                'params = ["date"]\n'
                "args = [\n"
                '  "--collect",\n'
                '  "--since", "{date}",\n'
                '  "--until", "{date}",\n'
                "]\n"
            ),
            encoding="utf-8",
        )

        assert load_shortcuts_config(path) == {
            "ob": ShortcutConfig(
                params=("date",),
                args=("--collect", "--since", "{date}", "--until", "{date}"),
            )
        }

    def test_mask_api_key(self):
        assert mask_api_key("") == ""
        assert mask_api_key("abcdef") == "******"
        assert mask_api_key("sk-123456789") == "sk-******789"


class TestConfigCommand:
    def test_view_existing(self, tmp_path, capsys, monkeypatch):
        path = tmp_path / "config.toml"
        default_log_path = tmp_path / "logs" / "collect.log"
        path.write_text(
            (
                "[ai]\n"
                'provider = "openai"\n'
                'base_url = "https://api.openai.com/v1"\n'
                'model = "gpt-4.1-mini"\n'
                'api_key = "sk-test-123"\n'
                "\n[shortcut.ob]\n"
                'params = ["date"]\n'
                'args = ["--collect", "--since", "{date}", "--until", "{date}"]\n'
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("agent_dump.config.get_config_path", lambda **kwargs: path)

        result = handle_config_command("view")
        assert result == 0
        out = capsys.readouterr().out
        assert "当前配置" in out
        assert "sk-*****123" in out
        assert "collect.summary_concurrency: 4" in out
        assert "collect.summary_timeout_seconds: 90" in out
        assert "logging.enabled: True" in out
        assert f"logging.path: {default_log_path}" in out
        assert "shortcuts.count: 1" in out
        assert "shortcut.ob:" in out

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

    def test_write_ai_config_preserves_collect_and_logging_sections(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[collect]\n"
                "summary_concurrency = 8\n"
                "summary_timeout_seconds = 180\n"
                "\n[logging]\n"
                "enabled = false\n"
                'path = "/tmp/collect.log"\n'
                "\n[shortcut.ob]\n"
                'params = ["date"]\n'
                'args = ["--collect", "--since", "{date}", "--until", "{date}"]\n'
            ),
            encoding="utf-8",
        )

        write_ai_config(
            AIConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4.1-mini",
                api_key="sk-test-123",
            ),
            path,
        )

        assert load_collect_config(path) == CollectConfig(summary_concurrency=8, summary_timeout_seconds=180)
        assert load_logging_config(path) == LoggingConfig(enabled=False, path=Path("/tmp/collect.log"))
        assert load_shortcuts_config(path) == {
            "ob": ShortcutConfig(
                params=("date",),
                args=("--collect", "--since", "{date}", "--until", "{date}"),
            )
        }

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
