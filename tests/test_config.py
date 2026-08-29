"""配置模块测试。"""

from collections.abc import Callable
import os
from pathlib import Path
from typing import Any
from unittest import mock

from locale_helpers import Keys, expect_contains
import pytest

import agent_dump.config as config_module
from agent_dump.config import (
    MAX_COLLECT_SUMMARY_CONCURRENCY,
    AIConfig,
    AIConfigError,
    CollectConfig,
    ConfigurationParseMode,
    ExportConfig,
    LoggingConfig,
    ShortcutConfig,
    get_config_path,
    load_ai_config,
    load_collect_config,
    load_config_document,
    load_export_config,
    load_logging_config,
    load_shortcuts_config,
    tomllib,
    validate_ai_config,
    write_ai_config,
    write_config,
)
from agent_dump.config_command import handle_config_command, mask_api_key, prompt_edit_config
from agent_dump.text_safety import has_unsafe_body_characters


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
    def test_document_records_source_presence(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"

        assert load_config_document(path).source_exists is False

        path.touch()

        assert load_config_document(path).source_exists is True

    @pytest.mark.parametrize(
        "loader",
        [
            load_ai_config,
            load_collect_config,
            load_logging_config,
            load_export_config,
            load_shortcuts_config,
        ],
    )
    def test_invalid_toml_is_not_silently_projected(
        self,
        tmp_path: Path,
        loader: Callable[[Path | None], object],
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_text('[export\noutput = "./exports"\n', encoding="utf-8")

        with pytest.raises(ValueError, match="not valid TOML"):
            loader(path)

    @pytest.mark.parametrize("deny", ['"/private"', '["/private", 42]', '[""]', '["   "]', '["\\u0000"]'])
    def test_collect_safety_rejects_invalid_exclusions(self, tmp_path: Path, deny: str) -> None:
        path = tmp_path / "config.toml"
        path.write_text(f"[agent.codex]\ndeny = {deny}\n", encoding="utf-8")

        with pytest.raises(ValueError, match=r"agent\.codex\.deny"):
            load_config_document(path).validate_collect_safety()

    def test_collect_safety_rejects_invalid_parse(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text("[collect]\nsummary_concurrency = 4oops\n", encoding="utf-8")

        with pytest.raises(ValueError, match="TOML"):
            load_config_document(path).validate_collect_safety()

    @pytest.mark.parametrize(
        "settings", ["", "[agent.codex]\ndeny = []\n", '[agent.codex]\ndeny = ["/private, work"]\n']
    )
    def test_collect_safety_accepts_valid_exclusions(self, tmp_path: Path, settings: str) -> None:
        path = tmp_path / "config.toml"
        path.write_text(settings, encoding="utf-8")

        load_config_document(path).validate_collect_safety()

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
        assert load_export_config(path) == ExportConfig()

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
            ('[collect]\nsummary_concurrency = 8\n\n[agent.claudecode]\ndeny = [\n  "/repo/a",\n  "/repo/b/sub"\n]\n'),
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

    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            (MAX_COLLECT_SUMMARY_CONCURRENCY, MAX_COLLECT_SUMMARY_CONCURRENCY),
            (MAX_COLLECT_SUMMARY_CONCURRENCY + 1, CollectConfig().summary_concurrency),
        ],
    )
    def test_load_collect_config_bounds_summary_concurrency(self, tmp_path, configured, expected):
        path = tmp_path / "config.toml"
        path.write_text(f"[collect]\nsummary_concurrency = {configured}\n", encoding="utf-8")

        assert load_collect_config(path).summary_concurrency == expected

    def test_load_collect_config_ignores_invalid_agent_deny(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            ('[collect]\nsummary_concurrency = 2\n\n[agent.claudecode]\ndeny = "bad"\n\n[agent.codex]\ndeny = []\n'),
            encoding="utf-8",
        )

        assert load_collect_config(path) == CollectConfig(summary_concurrency=2)

    def test_load_logging_config_reads_values(self, tmp_path):
        path = tmp_path / "config.toml"
        log_path = tmp_path / "logs" / "collect.jsonl"
        path.write_text(
            (f'[logging]\nenabled = false\npath = "{log_path}"\n'),
            encoding="utf-8",
        )

        assert load_logging_config(path) == LoggingConfig(enabled=False, path=log_path)

    def test_load_logging_config_defaults_to_config_dir(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        monkeypatch.setattr("agent_dump.config.get_config_path", lambda **kwargs: path)

        assert load_logging_config(path) == LoggingConfig(enabled=True, path=tmp_path / "logs" / "collect.log")

    def test_load_export_config_reads_output(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            ('[export]\noutput = "../exports"\n'),
            encoding="utf-8",
        )

        assert load_export_config(path) == ExportConfig(output="../exports")

    def test_load_shortcuts_config_reads_shortcuts(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            ('[shortcut.ob]\nparams = ["date"]\nargs = ["--collect", "--since", "{date}", "--until", "{date}"]\n'),
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

    def test_load_ai_config_preserves_hash_in_quoted_value(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                "[ai]\n"
                'provider = "openai"\n'
                'base_url = "https://api.openai.com/v1"\n'
                'model = "gpt-4.1-mini"\n'
                'api_key = "sk-abc#def"  # trailing comment\n'
            ),
            encoding="utf-8",
        )

        config = load_ai_config(path)
        assert config is not None
        assert config.api_key == "sk-abc#def"

    def test_load_collect_config_deny_path_containing_comma(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            ('[agent.claudecode]\ndeny = ["/repo/a, with comma", "/repo/b"]\n'),
            encoding="utf-8",
        )

        assert load_collect_config(path) == CollectConfig(
            agent_denies={"claudecode": ("/repo/a, with comma", "/repo/b")},
        )

    def test_load_falls_back_to_lenient_parser_for_invalid_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        # 旧版本写出的 Windows 路径未转义反斜杠，不是合法 TOML
        path.write_text(
            ('[logging]\nenabled = false\npath = "C:\\Users\\kevin\\collect.log"\n'),
            encoding="utf-8",
        )

        config = load_logging_config(path)
        assert config.enabled is False
        assert config.path == Path("C:\\Users\\kevin\\collect.log")

    def test_write_and_load_round_trip_special_characters(self, tmp_path):
        path = tmp_path / "config.toml"
        original = AIConfig(
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key='sk-"quoted"#hash\\slash',
        )
        write_ai_config(original, path)

        assert load_ai_config(path) == original

    def test_write_preserves_unknown_keys_sections_and_nested_tables(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            (
                'root_feature = "keep"\n'
                "\n[ai]\n"
                'provider = "openai"\n'
                'base_url = "https://old.example/v1"\n'
                'model = "old-model"\n'
                'api_key = "old-key"\n'
                'future_knob = "keep"\n'
                "\n[collect]\n"
                "summary_concurrency = 8\n"
                'future_mode = "keep"\n'
                "\n[future]\n"
                "enabled = true\n"
                'flags = ["a", "b"]\n'
                'rules = [{ name = "first", enabled = true }]\n'
                "\n[future.nested]\n"
                'mode = "keep"\n'
            ),
            encoding="utf-8",
        )

        write_ai_config(
            AIConfig(
                provider="anthropic",
                base_url="https://api.anthropic.com/v1",
                model="claude",
                api_key="new-key",
            ),
            path,
        )

        document = load_config_document(path)
        assert document.ai_config() == AIConfig(
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude",
            api_key="new-key",
        )
        assert document.sections[()]["root_feature"] == "keep"
        assert document.sections[("ai",)]["future_knob"] == "keep"
        assert document.sections[("collect",)]["future_mode"] == "keep"
        assert document.sections[("future",)] == {
            "enabled": True,
            "flags": ["a", "b"],
            "rules": [{"name": "first", "enabled": True}],
        }
        assert document.sections[("future", "nested")] == {"mode": "keep"}
        assert ("logging",) not in document.sections
        assert ("export",) not in document.sections

    def test_write_preserves_comments_spacing_and_order(self, tmp_path):
        path = tmp_path / "config.toml"
        original = (
            "# user configuration\n"
            "\n"
            "[ai] # provider settings\n"
            'provider   = "openai"  # keep provider note\n'
            'base_url = "https://old.example/v1"\n'
            'model = "old-model"\n'
            'api_key = "old-key" # rotate manually\n'
            "\n"
            "[future]\n"
            "enabled    = true # keep alignment\n"
            "\n"
            "[export] # output settings\n"
            'output    = "./old" # keep output note\n'
        )
        path.write_text(original, encoding="utf-8")
        document = load_config_document(path)

        write_config(
            AIConfig(
                provider="anthropic",
                base_url="https://new.example/v1",
                model="claude",
                api_key="new-key",
            ),
            ExportConfig(output="./new"),
            path,
            document=document,
        )

        expected = (
            original.replace('"openai"', '"anthropic"')
            .replace('"https://old.example/v1"', '"https://new.example/v1"')
            .replace('"old-model"', '"claude"')
            .replace('"old-key"', '"new-key"')
            .replace('"./old"', '"./new"')
        )
        assert path.read_text(encoding="utf-8") == expected

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
    def test_write_config_restricts_permissions(self, tmp_path):
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

        assert path.stat().st_mode & 0o777 == 0o600

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
    def test_write_config_is_private_when_created(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        created_modes: list[int] = []
        original_fdopen = os.fdopen

        def recording_fdopen(descriptor: int, *args: Any, **kwargs: Any):
            created_modes.append(os.fstat(descriptor).st_mode & 0o777)
            return original_fdopen(descriptor, *args, **kwargs)

        monkeypatch.setattr("agent_dump.private_files.os.fdopen", recording_fdopen)
        previous_umask = os.umask(0o022)
        try:
            write_ai_config(
                AIConfig(
                    provider="openai",
                    base_url="https://api.openai.com/v1",
                    model="gpt-4.1-mini",
                    api_key="sk-test-123",
                ),
                path,
            )
        finally:
            os.umask(previous_umask)

        assert created_modes == [0o600]

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
    def test_write_config_restricts_existing_file_before_overwrite(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("", encoding="utf-8")
        path.chmod(0o644)

        write_ai_config(
            AIConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4.1-mini",
                api_key="sk-test-123",
            ),
            path,
        )

        assert path.stat().st_mode & 0o777 == 0o600

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
                "\n[export]\n"
                'output = "../exports"\n'
                "\n[shortcut.ob]\n"
                'params = ["date"]\n'
                'args = ["--collect", "--since", "{date}", "--until", "{date}"]\n'
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("agent_dump.config_command.get_config_path", lambda **kwargs: path)

        with mock.patch(
            "agent_dump.config._read_config_sections",
            wraps=config_module._read_config_sections,
        ) as read_sections:
            result = handle_config_command("view")

        assert result == 0
        read_sections.assert_called_once_with(path)
        out = capsys.readouterr().out
        assert "当前配置" in out
        assert "sk-*****123" in out
        assert "export.output: ../exports" in out
        assert "collect.summary_concurrency: 4" in out
        assert "collect.summary_timeout_seconds: 90" in out
        assert "logging.enabled: True" in out
        assert f"logging.path: {default_log_path}" in out
        assert "shortcuts.count: 1" in out
        assert "shortcut.ob:" in out

    def test_view_sanitizes_config_paths_models_and_shortcuts(self, tmp_path, capsys, monkeypatch):
        poison = "value\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        path = tmp_path / "config.toml"
        path.touch()
        document = mock.MagicMock()
        document.ai_config.return_value = AIConfig(poison, poison, poison, poison)
        document.export_config.return_value = ExportConfig(output=poison)
        document.collect_config.return_value = CollectConfig()
        document.logging_config.return_value = LoggingConfig(path=Path(poison))
        document.shortcuts_config.return_value = {
            poison: ShortcutConfig(params=(poison,), args=(poison,)),
        }
        monkeypatch.setattr("agent_dump.config_command.get_config_path", lambda **kwargs: path)
        monkeypatch.setattr("agent_dump.config_command.load_config_document", lambda _path: document)

        result = handle_config_command("view")

        output = capsys.readouterr().out
        assert result == 0
        assert not has_unsafe_body_characters(output)
        assert "FORGED" in output

    def test_view_missing_then_create(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        monkeypatch.setattr("agent_dump.config_command.get_config_path", lambda **kwargs: path)
        monkeypatch.setattr(
            "agent_dump.config_command.prompt_edit_config",
            lambda existing_ai=None, existing_export=None: (
                AIConfig(
                    provider="anthropic",
                    base_url="https://api.anthropic.com/v1",
                    model="claude-3-7-sonnet",
                    api_key="ak-test",
                ),
                ExportConfig(output="./exports"),
            ),
        )

        result = handle_config_command("view", input_fn=lambda _: "y")
        assert result == 0
        assert path.exists()
        saved = load_ai_config(path)
        assert saved is not None
        assert saved.provider == "anthropic"
        assert load_export_config(path) == ExportConfig(output="./exports")

    def test_edit_cancelled(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        monkeypatch.setattr("agent_dump.config_command.get_config_path", lambda **kwargs: path)
        monkeypatch.setattr(
            "agent_dump.config_command.prompt_edit_config",
            lambda existing_ai=None, existing_export=None: (None, existing_export or ExportConfig()),
        )

        result = handle_config_command("edit")
        assert result == 1
        assert not path.exists()

    def test_edit_rejects_invalid_toml_without_prompting_or_rewriting(self, tmp_path, capsys, monkeypatch):
        path = tmp_path / "config.toml"
        original = '[export]\noutput = "C:\\Users\\kevin\\dumps"\n\n[plugin]\ntoken = "abc#def"\n'
        path.write_text(original, encoding="utf-8")
        monkeypatch.setattr("agent_dump.config_command.get_config_path", lambda **kwargs: path)

        with mock.patch("agent_dump.config_command.prompt_edit_config") as prompt:
            result = handle_config_command("edit")

        assert result == 1
        prompt.assert_not_called()
        assert path.read_text(encoding="utf-8") == original
        assert expect_contains(capsys.readouterr().out, Keys.CONFIG_EDIT_REQUIRES_VALID_TOML, path=path)

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
        assert load_export_config(path) == ExportConfig()
        assert load_shortcuts_config(path) == {
            "ob": ShortcutConfig(
                params=("date",),
                args=("--collect", "--since", "{date}", "--until", "{date}"),
            )
        }

    def test_write_config_preserves_export_collect_and_logging_sections(self, tmp_path):
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

        write_config(None, ExportConfig(output="../exports"), path)

        assert load_ai_config(path) is None
        assert load_collect_config(path) == CollectConfig(summary_concurrency=8, summary_timeout_seconds=180)
        assert load_logging_config(path) == LoggingConfig(enabled=False, path=Path("/tmp/collect.log"))
        assert load_export_config(path) == ExportConfig(output="../exports")

    def test_handle_config_command_allows_export_only_config(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        monkeypatch.setattr("agent_dump.config_command.get_config_path", lambda **kwargs: path)
        monkeypatch.setattr(
            "agent_dump.config_command.prompt_edit_config",
            lambda existing_ai=None, existing_export=None: (None, ExportConfig(output="./exports")),
        )

        result = handle_config_command("edit")

        assert result == 0
        assert load_ai_config(path) is None
        assert load_export_config(path) == ExportConfig(output="./exports")

    def test_invalid_action(self):
        result = handle_config_command("bad-action", input_fn=lambda _: "n")
        assert result == 1

    def test_prompt_edit_simple_mode(self, monkeypatch):
        monkeypatch.setattr("agent_dump.config_command._is_terminal", lambda: False)
        inputs = iter(["1", "https://api.openai.com/v1", "gpt-4.1-mini", "sk-123", "./exports", "y"])
        with mock.patch("builtins.input", side_effect=lambda _="": next(inputs)):
            edited_ai, edited_export = prompt_edit_config()

        assert edited_ai is not None
        assert edited_ai.provider == "openai"
        assert edited_ai.model == "gpt-4.1-mini"
        assert edited_export == ExportConfig(output="./exports")

    def test_prompt_edit_hides_api_key_when_only_stdin_is_a_terminal(self, monkeypatch):
        monkeypatch.setattr("agent_dump.config_command._is_terminal", lambda: False)
        monkeypatch.setattr("agent_dump.config_command.os.isatty", lambda fd: fd == 0)
        inputs = iter(["1", "https://api.openai.com/v1", "gpt-4.1-mini", "./exports", "y"])

        with (
            mock.patch("builtins.input", side_effect=lambda _="": next(inputs)) as visible_input,
            mock.patch("agent_dump.config_command.getpass.getpass", return_value="sk-hidden") as secret_input,
        ):
            edited_ai, edited_export = prompt_edit_config()

        assert edited_ai is not None
        assert edited_ai.api_key == "sk-hidden"
        assert edited_export == ExportConfig(output="./exports")
        secret_input.assert_called_once()
        assert all("API Key" not in str(call.args[0]) for call in visible_input.call_args_list)


class TestAiBaseUrlSchemeValidation:
    """AD-130：base_url 的 scheme 必须先过白名单，明文带 key 要失败关闭。"""

    @staticmethod
    def _config(base_url: str, api_key: str = "sk-test") -> AIConfig:
        return AIConfig(provider="openai", base_url=base_url, model="m", api_key=api_key)

    def test_missing_config_reports_typed_error(self):
        valid, errors = validate_ai_config(None, config_file_exists=False)

        assert not valid
        assert errors == [AIConfigError.MISSING_FILE]

    def test_missing_ai_section_reports_missing_fields(self):
        valid, errors = validate_ai_config(None)

        assert not valid
        assert errors == [
            AIConfigError.PROVIDER,
            AIConfigError.BASE_URL,
            AIConfigError.MODEL,
            AIConfigError.API_KEY,
        ]

    @pytest.mark.parametrize(
        "base_url",
        ["https://api.example.com/v1", "https://api.example.com", "HTTPS://API.EXAMPLE.COM/v1"],
    )
    def test_https_is_accepted(self, base_url):
        valid, errors = validate_ai_config(self._config(base_url))

        assert valid, errors

    @pytest.mark.parametrize(
        "base_url",
        ["file:///etc/passwd", "ftp://example.com", "gopher://example.com", "not-a-url"],
    )
    def test_non_http_schemes_are_rejected(self, base_url):
        """未加白名单前这些值也能到达 urllib 的 opener。"""
        valid, errors = validate_ai_config(self._config(base_url))

        assert not valid
        assert AIConfigError.BASE_URL_SCHEME in errors

    @pytest.mark.parametrize("base_url", ["http://api.example.com/v1", "http://10.0.0.5:8080/v1"])
    def test_http_with_a_key_to_a_remote_host_is_rejected(self, base_url):
        valid, errors = validate_ai_config(self._config(base_url))

        assert not valid
        assert AIConfigError.BASE_URL_PLAINTEXT_KEY in errors

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://localhost:11434/v1",
            "http://127.0.0.1:8000/v1",
            "http://[::1]:8000/v1",
            "http://LOCALHOST:1234/v1",
        ],
    )
    def test_http_to_loopback_is_allowed(self, base_url):
        """本机 gateway 是明文的正当用例，必须留出这个口子。"""
        valid, errors = validate_ai_config(self._config(base_url))

        assert valid, errors

    def test_http_without_a_key_reports_the_missing_key_not_the_scheme(self):
        valid, errors = validate_ai_config(self._config("http://api.example.com/v1", api_key=""))

        assert not valid
        assert AIConfigError.API_KEY in errors
        assert AIConfigError.BASE_URL_PLAINTEXT_KEY not in errors


class TestTableKeyPathsSurviveRoundTrip:
    """AD-164：所有合法 TOML table key segment 必须原样保持语义。"""

    @staticmethod
    def _round_trip(tmp_path: Path, original: str) -> tuple[dict, dict]:
        config_path = tmp_path / "config.toml"
        config_path.write_text(original, encoding="utf-8")
        document = load_config_document(config_path)
        write_config(document.ai_config(), path=config_path, document=document)
        return tomllib.loads(original), tomllib.loads(config_path.read_text(encoding="utf-8"))

    def test_quoted_dotted_key_stays_one_segment(self, tmp_path):
        before, after = self._round_trip(tmp_path, '["plugin.with.dot"]\nenabled = true\n')

        assert after == before
        assert "plugin.with.dot" in after, "含点的引号 key 不得被拆成三层表"
        assert "plugin" not in after

    def test_empty_table_is_preserved(self, tmp_path):
        before, after = self._round_trip(tmp_path, "[empty]\n\n[other]\nx = 1\n")

        assert after == before
        assert after["empty"] == {}

    def test_nested_empty_table_is_preserved(self, tmp_path):
        before, after = self._round_trip(tmp_path, "[a.b.c]\n")

        assert after == before

    def test_array_of_tables_stays_equivalent(self, tmp_path):
        before, after = self._round_trip(tmp_path, '[[items]]\nname = "one"\n\n[[items]]\nname = "two"\n')

        assert after == before

    def test_mixed_nesting_stays_equivalent(self, tmp_path):
        original = 'root = "top"\n\n[a]\nx = 1\n\n[a.b]\ny = 2\n\n["a.b"]\nz = 3\n\n[empty]\n\n["quoted key"]\nw = 4\n'

        before, after = self._round_trip(tmp_path, original)

        assert after == before
        assert after["a"] == {"x": 1, "b": {"y": 2}}
        assert after["a.b"] == {"z": 3}, '[a.b] 与 ["a.b"] 是两张不同的表'
        assert after["quoted key"] == {"w": 4}

    def test_windows_path_values_survive(self, tmp_path):
        original = '[export]\noutput = "C:\\\\Users\\\\kevin\\\\dumps"\n'

        before, after = self._round_trip(tmp_path, original)

        assert after == before

    def test_known_projections_still_work(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[ai]\nprovider = "openai"\nbase_url = "https://x"\nmodel = "m"\napi_key = "k"\n\n'
            "[collect]\nsummary_concurrency = 4\n\n"
            '[agent.claudecode]\ndeny = ["a", "b"]\n\n'
            '[shortcut.today]\nparams = ["x"]\nargs = ["--days", "1"]\n\n'
            "[logging]\nenabled = false\n\n"
            '[export]\noutput = "/tmp/out"\n',
            encoding="utf-8",
        )

        document = load_config_document(config_path)

        ai = document.ai_config()
        assert ai is not None and ai.provider == "openai"
        collect = document.collect_config()
        assert collect.summary_concurrency == 4
        assert collect.agent_denies == {"claudecode": ("a", "b")}
        assert document.shortcuts_config()["today"].args == ("--days", "1")
        assert document.logging_config().enabled is False
        assert document.export_config().output == "/tmp/out"

    def test_legacy_windows_path_recovery_preserves_toml_values(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[ai]\napi_key = "abc#def"\n\n'
            '[shortcut.demo]\nparams = []\nargs = ["--query", "a,b"]\n\n'
            '[export]\noutput = "C:\\Users\\kevin"\n\n'
            '["plugin.with.dot"]\nenabled = true\n',
            encoding="utf-8",
        )

        document = load_config_document(config_path)

        assert document.parse_mode is ConfigurationParseMode.LEGACY
        assert document.sections[("ai",)]["api_key"] == "abc#def"
        assert document.shortcuts_config()["demo"].args == ("--query", "a,b")
        assert document.export_config().output == "C:\\Users\\kevin"
        assert ("export",) in document.sections
        assert ("plugin.with.dot",) in document.sections
        assert ("plugin",) not in document.sections

    def test_invalid_toml_does_not_expose_partial_values(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[ai]\napi_key = "abc#def"\n\n[collect]\nsummary_concurrency = 4oops\n',
            encoding="utf-8",
        )

        document = load_config_document(config_path)

        assert document.parse_mode is ConfigurationParseMode.INVALID
        assert document.sections == {}
        assert document.ai_config() is None

    def test_legacy_document_cannot_be_rewritten_lossily(self, tmp_path):
        config_path = tmp_path / "config.toml"
        original = '[export]\noutput = "C:\\Users\\kevin\\dumps"\n\n[plugin]\ntoken = "abc#def"\nitems = ["a,b", "c"]\n'
        config_path.write_text(original, encoding="utf-8")
        document = load_config_document(config_path)

        assert document.sections[("plugin",)]["token"].split("#") == ["abc", "def"]
        assert document.sections[("plugin",)]["items"] == ["a,b", "c"]

        with pytest.raises(ValueError, match="valid TOML"):
            write_config(document.ai_config(), path=config_path, document=document)

        assert config_path.read_text(encoding="utf-8") == original
