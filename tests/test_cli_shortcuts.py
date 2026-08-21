"""Shortcut expansion and dispatch tests."""

from pathlib import Path
from unittest import mock

from locale_helpers import Keys as LocaleKeys, expect
import pytest

from agent_dump.cli import (
    expand_shortcut_argv,
    main,
)
from agent_dump.command_plan import (
    CollectOperation,
)
from agent_dump.shortcut import ShortcutErrorCode, ShortcutExpansionError
from agent_dump.text_safety import has_unsafe_body_characters


class TestShortcutExpansion:
    def test_expand_shortcut_argv_does_not_load_config_for_ordinary_commands(self):
        with mock.patch("agent_dump.cli.load_shortcuts_config") as load_shortcuts:
            argv = expand_shortcut_argv(["--list"])

        assert argv == ["--list"]
        load_shortcuts.assert_not_called()

    def test_expand_shortcut_argv_collect_date(self, monkeypatch):
        monkeypatch.setattr(
            "agent_dump.cli.load_shortcuts_config",
            lambda: {
                "ob": mock.MagicMock(
                    params=("date",),
                    args=(
                        "--collect",
                        "--save",
                        "~/Dropbox/OBSIDIAN/XingKaiXin/00_Inbox/{year}/{year_month}/agent-dump-collect-{date}.md",
                        "--since",
                        "{date}",
                        "--until",
                        "{date}",
                    ),
                )
            },
        )

        expanded = expand_shortcut_argv(["--shortcut", "ob", "20260408"])

        assert expanded == [
            "--collect",
            "--save",
            str(
                Path("~/Dropbox/OBSIDIAN/XingKaiXin/00_Inbox/2026/2026-04/agent-dump-collect-20260408.md").expanduser()
            ),
            "--since",
            "20260408",
            "--until",
            "20260408",
        ]

    def test_expand_shortcut_argv_keeps_remaining_args(self, monkeypatch):
        monkeypatch.setattr(
            "agent_dump.cli.load_shortcuts_config",
            lambda: {
                "ob": mock.MagicMock(
                    params=("date",),
                    args=("--collect", "--since", "{date}", "--until", "{date}"),
                )
            },
        )

        expanded = expand_shortcut_argv(["--shortcut", "ob", "20260408", "--lang", "zh"])

        assert expanded == ["--collect", "--since", "20260408", "--until", "20260408", "--lang", "zh"]

    def test_expand_shortcut_argv_rejects_unknown_variable(self, monkeypatch):
        monkeypatch.setattr(
            "agent_dump.cli.load_shortcuts_config",
            lambda: {
                "ob": mock.MagicMock(
                    params=("date",),
                    args=("--collect", "--since", "{since}"),
                )
            },
        )

        with pytest.raises(ShortcutExpansionError) as exc_info:
            expand_shortcut_argv(["--shortcut", "ob", "20260408"])

        assert exc_info.value.code is ShortcutErrorCode.UNKNOWN_VARIABLE
        assert exc_info.value.variable_name == "since"

    def test_expand_shortcut_argv_rejects_malformed_template(self, monkeypatch):
        monkeypatch.setattr(
            "agent_dump.cli.load_shortcuts_config",
            lambda: {"broken": mock.MagicMock(params=(), args=("--output", "{missing"))},
        )

        with pytest.raises(ShortcutExpansionError) as exc_info:
            expand_shortcut_argv(["--shortcut", "broken"])

        assert exc_info.value.code is ShortcutErrorCode.TEMPLATE_INVALID


class TestMain:
    def test_main_expands_shortcut_before_collect(self):
        with (
            mock.patch(
                "agent_dump.cli.expand_shortcut_argv",
                return_value=["--collect", "--since", "20260408", "--until", "20260408"],
            ),
            mock.patch("agent_dump.cli.handle_collect_mode", return_value=0) as mock_handle,
        ):
            with mock.patch("sys.argv", ["agent-dump", "--shortcut", "ob", "20260408"]):
                result = main()

        assert result == 0
        operation = mock_handle.call_args.args[0]
        assert isinstance(operation, CollectOperation)
        assert operation.since == "20260408"
        assert operation.until == "20260408"

    @pytest.mark.parametrize(
        ("trailing_args", "expected_language"),
        [
            ([], "en"),
            (["--lang", "zh"], "zh"),
        ],
    )
    def test_main_uses_the_effective_language_after_shortcut_expansion(
        self,
        trailing_args,
        expected_language,
        use_language,
    ):
        from agent_dump.i18n import i18n

        use_language("zh")
        shortcut = mock.MagicMock(params=(), args=("--providers", "--lang", "en"))
        with (
            mock.patch("agent_dump.cli.load_shortcuts_config", return_value={"status": shortcut}),
            mock.patch("agent_dump.cli.handle_providers_mode", return_value=0),
            mock.patch("sys.argv", ["agent-dump", "--shortcut", "status", *trailing_args]),
        ):
            result = main()

        assert result == 0
        assert i18n.lang == expected_language

    def test_main_reports_shortcut_not_found(self, capsys):
        error = ShortcutExpansionError(ShortcutErrorCode.NOT_FOUND, shortcut_name="ob")
        with mock.patch("agent_dump.cli.expand_shortcut_argv", side_effect=error):
            with mock.patch("sys.argv", ["agent-dump", "--shortcut", "ob", "20260408"]):
                result = main()

        assert result == 1
        assert expect(LocaleKeys.SHORTCUT_NOT_FOUND, name="ob") in capsys.readouterr().out

    def test_main_preserves_delimiters_in_shortcut_error_fields(self, capsys):
        error = ShortcutExpansionError(
            ShortcutErrorCode.ARGS_MISMATCH,
            shortcut_name="team:daily",
            expected=2,
            actual=1,
        )
        with mock.patch("agent_dump.cli.expand_shortcut_argv", side_effect=error):
            with mock.patch("sys.argv", ["agent-dump", "--shortcut", "team:daily"]):
                result = main()

        assert result == 1
        assert (
            expect(
                LocaleKeys.SHORTCUT_ARGS_MISMATCH,
                name="team:daily",
                expected=2,
                actual=1,
            )
            in capsys.readouterr().out
        )

    def test_main_sanitizes_shortcut_error_fields(self, capsys):
        poison = "name\x1b[2K\rFORGED\x1b]8;;https://example.invalid\x07link\u202e"
        error = ShortcutExpansionError(ShortcutErrorCode.NOT_FOUND, shortcut_name=poison)
        with mock.patch(
            "agent_dump.cli.expand_shortcut_argv",
            side_effect=error,
        ):
            with mock.patch("sys.argv", ["agent-dump", "--shortcut", poison]):
                result = main()

        output = capsys.readouterr().out
        assert result == 1
        assert not has_unsafe_body_characters(output)
        assert "FORGED" in output
