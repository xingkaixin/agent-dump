"""Interactive configuration command workflow."""

from collections.abc import Callable
import getpass
import os

import questionary
from questionary import Style

from agent_dump.config import (
    AIConfig,
    ConfigurationParseMode,
    ExportConfig,
    get_config_path,
    load_config_document,
    validate_ai_config,
    write_config,
)
from agent_dump.i18n import Keys, i18n
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import safe_display_text


def mask_api_key(value: str) -> str:
    """Mask API key for safe terminal display."""
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"


def _is_terminal() -> bool:
    return os.isatty(0) and os.isatty(1)


def _build_style() -> Style:
    return Style(
        [
            ("qmark", "fg:#673ab7 bold"),
            ("question", "bold"),
            ("answer", "fg:#f44336 bold"),
            ("pointer", "fg:#673ab7 bold"),
            ("highlighted", "noreverse"),
            ("selected", "noreverse"),
            ("instruction", ""),
            ("text", ""),
        ]
    )


def _ask_provider(default_provider: str) -> str | None:
    style = _build_style()
    choices = [
        questionary.Choice(title="OpenAI", value="openai"),
        questionary.Choice(title="Anthropic", value="anthropic"),
    ]
    q = questionary.select(
        i18n.t(Keys.CONFIG_SELECT_PROVIDER),
        choices=choices,
        default=default_provider if default_provider in {"openai", "anthropic"} else "openai",
        style=style,
    )
    return q.ask()


def _ask_text(prompt: str, default: str = "", *, secret: bool = False) -> str | None:
    style = _build_style()
    if secret:
        return questionary.password(safe_display_text(prompt), default=default, style=style).ask()
    safe_default = safe_display_text(default)
    result = questionary.text(safe_display_text(prompt), default=safe_default, style=style).ask()
    return default if result == safe_default else result


def _confirm(prompt: str, default: bool = True) -> bool:
    style = _build_style()
    result = questionary.confirm(safe_display_text(prompt), default=default, style=style).ask()
    return bool(result)


def _simple_select(prompt: str, options: list[tuple[str, str]], default_value: str) -> str | None:
    print(safe_display_text(prompt))
    for idx, (label, _) in enumerate(options, start=1):
        print(f"{idx}. {safe_display_text(label)}")
    raw = input(i18n.t(Keys.CONFIG_INPUT_PROMPT)).strip()
    if not raw:
        return default_value
    try:
        index = int(raw) - 1
    except ValueError:
        return None
    if index < 0 or index >= len(options):
        return None
    return options[index][1]


def _normalize_ai_candidate(candidate: AIConfig, existing: AIConfig | None) -> AIConfig | None:
    if candidate.base_url or candidate.model or candidate.api_key:
        return candidate
    if existing is not None:
        return candidate
    return None


def prompt_edit_config(
    existing_ai: AIConfig | None = None,
    existing_export: ExportConfig | None = None,
) -> tuple[AIConfig | None, ExportConfig]:
    """Interactive config edit flow, including default export output."""
    default_provider = existing_ai.provider if existing_ai else "openai"
    default_base_url = existing_ai.base_url if existing_ai else ""
    default_model = existing_ai.model if existing_ai else ""
    default_api_key = existing_ai.api_key if existing_ai else ""
    default_export_output = existing_export.output if existing_export is not None else ""

    if _is_terminal():
        provider = _ask_provider(default_provider)
        if provider is None:
            return (None, existing_export or ExportConfig())
        base_url = _ask_text(i18n.t(Keys.CONFIG_INPUT_BASE_URL), default_base_url)
        if base_url is None:
            return (None, existing_export or ExportConfig())
        model = _ask_text(i18n.t(Keys.CONFIG_INPUT_MODEL), default_model)
        if model is None:
            return (None, existing_export or ExportConfig())
        api_key = _ask_text(i18n.t(Keys.CONFIG_INPUT_API_KEY), default_api_key, secret=True)
        if api_key is None:
            return (None, existing_export or ExportConfig())
        export_output = _ask_text(i18n.t(Keys.CONFIG_INPUT_EXPORT_OUTPUT), default_export_output)
        if export_output is None:
            return (None, existing_export or ExportConfig())
    else:
        provider = _simple_select(
            i18n.t(Keys.CONFIG_SELECT_PROVIDER),
            [("OpenAI", "openai"), ("Anthropic", "anthropic")],
            default_provider,
        )
        if provider is None:
            return (None, existing_export or ExportConfig())
        base_url_input = input(
            f"{i18n.t(Keys.CONFIG_INPUT_BASE_URL)} [{safe_display_text(default_base_url)}]: "
        ).strip()
        model_input = input(f"{i18n.t(Keys.CONFIG_INPUT_MODEL)} [{safe_display_text(default_model)}]: ").strip()
        api_key_prompt = f"{i18n.t(Keys.CONFIG_INPUT_API_KEY)} [{safe_display_text(mask_api_key(default_api_key))}]: "
        api_key_input = getpass.getpass(api_key_prompt).strip() if os.isatty(0) else input(api_key_prompt).strip()
        export_output_input = input(
            f"{i18n.t(Keys.CONFIG_INPUT_EXPORT_OUTPUT)} [{safe_display_text(default_export_output)}]: "
        ).strip()
        base_url = base_url_input or default_base_url
        model = model_input or default_model
        api_key = api_key_input or default_api_key
        export_output = export_output_input or default_export_output

    ai_candidate = _normalize_ai_candidate(
        AIConfig(
            provider=provider.strip(),
            base_url=base_url.strip(),
            model=model.strip(),
            api_key=api_key.strip(),
        ),
        existing_ai,
    )
    export_candidate = ExportConfig(output=export_output.strip())

    print(i18n.t(Keys.CONFIG_CONFIRM_TITLE))
    print(
        render_terminal_message(
            Keys.CONFIG_CONFIRM_PROVIDER,
            provider=ai_candidate.provider if ai_candidate is not None else "",
        )
    )
    print(
        render_terminal_message(
            Keys.CONFIG_CONFIRM_BASE_URL,
            base_url=ai_candidate.base_url if ai_candidate is not None else "",
        )
    )
    print(
        render_terminal_message(
            Keys.CONFIG_CONFIRM_MODEL,
            model=ai_candidate.model if ai_candidate is not None else "",
        )
    )
    print(
        render_terminal_message(
            Keys.CONFIG_CONFIRM_API_KEY,
            api_key=mask_api_key(ai_candidate.api_key) if ai_candidate is not None else "",
        )
    )
    print(render_terminal_message(Keys.CONFIG_CONFIRM_EXPORT_OUTPUT, output=export_candidate.output))

    if _is_terminal():
        if not _confirm(i18n.t(Keys.CONFIG_CONFIRM_WRITE)):
            return (None, existing_export or ExportConfig())
    else:
        raw = input(f"{i18n.t(Keys.CONFIG_CONFIRM_WRITE)} (y/N): ").strip().lower()
        if raw not in {"y", "yes"}:
            return (None, existing_export or ExportConfig())

    return ai_candidate, export_candidate


def handle_config_command(action: str, *, input_fn: Callable[[str], str] = input) -> int:
    """Handle `--config view|edit` command flow."""
    config_path = get_config_path()
    document = load_config_document(config_path)
    existing = document.ai_config()
    existing_export = document.export_config()

    if action == "view":
        if not config_path.exists():
            print(render_terminal_message(Keys.CONFIG_NOT_FOUND, path=config_path))
            raw = input_fn(i18n.t(Keys.CONFIG_PROMPT_CREATE) + " (y/N): ").strip().lower()
            if raw not in {"y", "yes"}:
                return 1
            action = "edit"
        else:
            print(render_terminal_message(Keys.CONFIG_VIEW_TITLE, path=config_path))
            print(
                render_terminal_message(
                    Keys.CONFIG_CONFIRM_PROVIDER,
                    provider=existing.provider if existing is not None else "",
                )
            )
            print(
                render_terminal_message(
                    Keys.CONFIG_CONFIRM_BASE_URL,
                    base_url=existing.base_url if existing is not None else "",
                )
            )
            print(
                render_terminal_message(
                    Keys.CONFIG_CONFIRM_MODEL,
                    model=existing.model if existing is not None else "",
                )
            )
            print(
                render_terminal_message(
                    Keys.CONFIG_CONFIRM_API_KEY,
                    api_key=mask_api_key(existing.api_key) if existing is not None else "",
                )
            )
            print(
                render_terminal_message(
                    Keys.CONFIG_CONFIRM_EXPORT_OUTPUT,
                    output=existing_export.output or "./sessions (default)",
                )
            )
            collect_config = document.collect_config()
            logging_config = document.logging_config()
            shortcuts_config = document.shortcuts_config()
            print(f"  collect.summary_concurrency: {collect_config.summary_concurrency}")
            print(f"  collect.summary_timeout_seconds: {collect_config.summary_timeout_seconds}")
            print(f"  logging.enabled: {logging_config.enabled}")
            print(f"  logging.path: {safe_display_text(str(logging_config.path))}")
            print(f"  shortcuts.count: {len(shortcuts_config)}")
            for shortcut_name, shortcut in shortcuts_config.items():
                print(
                    safe_display_text(
                        f"  shortcut.{shortcut_name}: params={list(shortcut.params)} args={list(shortcut.args)}"
                    )
                )
            return 0

    if action != "edit":
        print(render_terminal_message(Keys.CONFIG_ACTION_INVALID, action=action))
        return 1

    if document.parse_mode is not ConfigurationParseMode.TOML:
        print(render_terminal_message(Keys.CONFIG_EDIT_REQUIRES_VALID_TOML, path=config_path))
        return 1

    edited_ai, edited_export = prompt_edit_config(existing, existing_export)
    if edited_ai is None and edited_export == existing_export:
        print(i18n.t(Keys.CONFIG_CANCELLED))
        return 1

    if edited_ai is None:
        ok, errors = True, []
    else:
        ok, errors = validate_ai_config(edited_ai)
    if not ok:
        print(render_terminal_message(Keys.CONFIG_INVALID_FIELDS, fields=", ".join(error.value for error in errors)))
        return 1

    path = write_config(edited_ai, edited_export, config_path, document=document)
    print(render_terminal_message(Keys.CONFIG_SAVED, path=path))
    return 0
