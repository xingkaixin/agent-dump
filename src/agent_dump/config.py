"""Configuration management for collect mode."""

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path

import questionary
from questionary import Style

from agent_dump.i18n import Keys, i18n


@dataclass(frozen=True)
class AIConfig:
    """AI provider configuration."""

    provider: str
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class CollectConfig:
    """Collect mode configuration."""

    summary_concurrency: int = 4


DEFAULT_COLLECT_SUMMARY_CONCURRENCY = 4


def get_config_path(
    *,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    is_windows: bool | None = None,
) -> Path:
    """Return config file path by platform defaults."""
    resolved_home = home if home is not None else Path.home()
    env = environ if environ is not None else os.environ

    resolved_is_windows = (os.name == "nt") if is_windows is None else is_windows

    if resolved_is_windows:
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "agent-dump" / "config.toml"
        local_appdata = env.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "agent-dump" / "config.toml"

    return resolved_home / ".config" / "agent-dump" / "config.toml"


def _strip_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _parse_simple_toml_sections(text: str) -> dict[str, dict[str, str]]:
    """Parse minimal TOML sections without third-party deps."""
    current_section: str | None = None
    parsed: dict[str, dict[str, str]] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            parsed.setdefault(current_section, {})
            continue

        if current_section is None:
            continue

        key, sep, value = line.partition("=")
        if not sep:
            continue

        normalized_key = key.strip()
        normalized_value = value.split("#", 1)[0].strip()
        parsed.setdefault(current_section, {})[normalized_key] = _strip_quotes(normalized_value)

    return parsed


def _read_config_sections(config_path: Path) -> dict[str, dict[str, str]]:
    return _parse_simple_toml_sections(config_path.read_text(encoding="utf-8"))


def load_ai_config(path: Path | None = None) -> AIConfig | None:
    """Load AI config if file exists and parseable."""
    config_path = path if path is not None else get_config_path()
    if not config_path.exists():
        return None

    parsed = _read_config_sections(config_path).get("ai", {})
    return AIConfig(
        provider=parsed.get("provider", "").strip(),
        base_url=parsed.get("base_url", "").strip(),
        model=parsed.get("model", "").strip(),
        api_key=parsed.get("api_key", "").strip(),
    )


def load_collect_config(path: Path | None = None) -> CollectConfig:
    """Load collect config with defaults for missing or invalid values."""
    config_path = path if path is not None else get_config_path()
    if not config_path.exists():
        return CollectConfig()

    parsed = _read_config_sections(config_path).get("collect", {})
    raw_concurrency = parsed.get("summary_concurrency", "").strip()
    if not raw_concurrency:
        return CollectConfig()

    try:
        concurrency = int(raw_concurrency)
    except ValueError:
        return CollectConfig()

    if concurrency <= 0:
        return CollectConfig()

    return CollectConfig(summary_concurrency=concurrency)


def validate_ai_config(config: AIConfig | None) -> tuple[bool, list[str]]:
    """Validate collect-required AI config."""
    if config is None:
        return False, ["missing_file"]

    errors: list[str] = []
    if config.provider not in {"openai", "anthropic"}:
        errors.append("provider")
    if not config.base_url:
        errors.append("base_url")
    if not config.model:
        errors.append("model")
    if not config.api_key:
        errors.append("api_key")

    return len(errors) == 0, errors


def mask_api_key(value: str) -> str:
    """Mask API key for safe terminal display."""
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"


def write_ai_config(config: AIConfig, path: Path | None = None) -> Path:
    """Persist AI config to TOML file."""
    config_path = path if path is not None else get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing_collect = load_collect_config(config_path)
    content = (
        "[ai]\n"
        f'provider = "{config.provider}"\n'
        f'base_url = "{config.base_url}"\n'
        f'model = "{config.model}"\n'
        f'api_key = "{config.api_key}"\n'
    )
    if config_path.exists() or existing_collect != CollectConfig():
        content += f"\n[collect]\nsummary_concurrency = {existing_collect.summary_concurrency}\n"
    config_path.write_text(content, encoding="utf-8")
    return config_path


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
        return questionary.password(prompt, default=default, style=style).ask()
    return questionary.text(prompt, default=default, style=style).ask()


def _confirm(prompt: str, default: bool = True) -> bool:
    style = _build_style()
    result = questionary.confirm(prompt, default=default, style=style).ask()
    return bool(result)


def _simple_select(prompt: str, options: list[tuple[str, str]], default_value: str) -> str | None:
    print(prompt)
    for idx, (label, _) in enumerate(options, start=1):
        print(f"{idx}. {label}")
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


def prompt_edit_ai_config(existing: AIConfig | None = None) -> AIConfig | None:
    """Interactive edit flow, with non-terminal fallback."""
    default_provider = existing.provider if existing else "openai"
    default_base_url = existing.base_url if existing else ""
    default_model = existing.model if existing else ""
    default_api_key = existing.api_key if existing else ""

    if _is_terminal():
        provider = _ask_provider(default_provider)
        if provider is None:
            return None
        base_url = _ask_text(i18n.t(Keys.CONFIG_INPUT_BASE_URL), default_base_url)
        if base_url is None:
            return None
        model = _ask_text(i18n.t(Keys.CONFIG_INPUT_MODEL), default_model)
        if model is None:
            return None
        api_key = _ask_text(i18n.t(Keys.CONFIG_INPUT_API_KEY), default_api_key, secret=True)
        if api_key is None:
            return None
    else:
        provider = _simple_select(
            i18n.t(Keys.CONFIG_SELECT_PROVIDER),
            [("OpenAI", "openai"), ("Anthropic", "anthropic")],
            default_provider,
        )
        if provider is None:
            return None
        base_url_input = input(f"{i18n.t(Keys.CONFIG_INPUT_BASE_URL)} [{default_base_url}]: ").strip()
        model_input = input(f"{i18n.t(Keys.CONFIG_INPUT_MODEL)} [{default_model}]: ").strip()
        api_key_input = input(f"{i18n.t(Keys.CONFIG_INPUT_API_KEY)} [{mask_api_key(default_api_key)}]: ").strip()
        base_url = base_url_input or default_base_url
        model = model_input or default_model
        api_key = api_key_input or default_api_key

    candidate = AIConfig(
        provider=provider.strip(),
        base_url=base_url.strip(),
        model=model.strip(),
        api_key=api_key.strip(),
    )

    print(i18n.t(Keys.CONFIG_CONFIRM_TITLE))
    print(i18n.t(Keys.CONFIG_CONFIRM_PROVIDER, provider=candidate.provider))
    print(i18n.t(Keys.CONFIG_CONFIRM_BASE_URL, base_url=candidate.base_url))
    print(i18n.t(Keys.CONFIG_CONFIRM_MODEL, model=candidate.model))
    print(i18n.t(Keys.CONFIG_CONFIRM_API_KEY, api_key=mask_api_key(candidate.api_key)))

    if _is_terminal():
        if not _confirm(i18n.t(Keys.CONFIG_CONFIRM_WRITE)):
            return None
    else:
        raw = input(f"{i18n.t(Keys.CONFIG_CONFIRM_WRITE)} (y/N): ").strip().lower()
        if raw not in {"y", "yes"}:
            return None

    return candidate


def handle_config_command(action: str, *, input_fn: Callable[[str], str] = input) -> int:
    """Handle `--config view|edit` command flow."""
    config_path = get_config_path()
    existing = load_ai_config(config_path)

    if action == "view":
        if existing is None:
            print(i18n.t(Keys.CONFIG_NOT_FOUND, path=str(config_path)))
            raw = input_fn(i18n.t(Keys.CONFIG_PROMPT_CREATE) + " (y/N): ").strip().lower()
            if raw not in {"y", "yes"}:
                return 1
            action = "edit"
        else:
            print(i18n.t(Keys.CONFIG_VIEW_TITLE, path=str(config_path)))
            print(i18n.t(Keys.CONFIG_CONFIRM_PROVIDER, provider=existing.provider or ""))
            print(i18n.t(Keys.CONFIG_CONFIRM_BASE_URL, base_url=existing.base_url or ""))
            print(i18n.t(Keys.CONFIG_CONFIRM_MODEL, model=existing.model or ""))
            print(i18n.t(Keys.CONFIG_CONFIRM_API_KEY, api_key=mask_api_key(existing.api_key)))
            collect_config = load_collect_config(config_path)
            print(f"  collect.summary_concurrency: {collect_config.summary_concurrency}")
            return 0

    if action != "edit":
        print(i18n.t(Keys.CONFIG_ACTION_INVALID, action=action))
        return 1

    edited = prompt_edit_ai_config(existing)
    if edited is None:
        print(i18n.t(Keys.CONFIG_CANCELLED))
        return 1

    ok, errors = validate_ai_config(edited)
    if not ok:
        print(i18n.t(Keys.CONFIG_INVALID_FIELDS, fields=", ".join(errors)))
        return 1

    path = write_ai_config(edited, config_path)
    print(i18n.t(Keys.CONFIG_SAVED, path=str(path)))
    return 0
