"""Configuration models, parsing, validation, and persistence."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit

from agent_dump.private_files import PRIVATE_FILE_MODE

if sys.version_info >= (3, 11):
    import tomllib
else:
    # Python 3.10 无 tomllib；手写解析器无法正确处理引号内的 '#' 与转义，必须用标准解析器
    import tomli as tomllib


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
    summary_timeout_seconds: int = 90
    agent_denies: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class LoggingConfig:
    """Logging configuration for collect diagnostics."""

    enabled: bool = True
    path: Path | None = None


@dataclass(frozen=True)
class ExportConfig:
    """Default export directory configuration."""

    output: str = ""


@dataclass(frozen=True)
class ShortcutConfig:
    """One shortcut preset configuration."""

    params: tuple[str, ...] = ()
    args: tuple[str, ...] = ()


class ConfigurationParseMode(Enum):
    """How a configuration snapshot was parsed."""

    TOML = "toml"
    LEGACY = "legacy"


@dataclass(frozen=True)
class ConfigurationDocument:
    """One parsed configuration snapshot."""

    path: Path
    # key 是结构化的 table path，不是点连接字符串：TOML 里 ["plugin.with.dot"] 是一个
    # 含点的 key，[plugin.with.dot] 是三层表。拼成 "plugin.with.dot" 之后无从分辨，
    # 写回时按 "." 拆分就会把前者变成后者。空 tuple 是根表。
    sections: dict[tuple[str, ...], dict[str, Any]]
    parse_mode: ConfigurationParseMode = ConfigurationParseMode.TOML

    def ai_config(self) -> AIConfig | None:
        parsed = self.sections.get(("ai",))
        if parsed is None:
            return None
        provider = parsed.get("provider", "")
        base_url = parsed.get("base_url", "")
        model = parsed.get("model", "")
        api_key = parsed.get("api_key", "")
        return AIConfig(
            provider=provider.strip() if isinstance(provider, str) else "",
            base_url=base_url.strip() if isinstance(base_url, str) else "",
            model=model.strip() if isinstance(model, str) else "",
            api_key=api_key.strip() if isinstance(api_key, str) else "",
        )

    def collect_config(self) -> CollectConfig:
        parsed = self.sections.get(("collect",), {})
        concurrency = _coerce_positive_int(
            parsed.get("summary_concurrency"),
            DEFAULT_COLLECT_SUMMARY_CONCURRENCY,
        )
        timeout_seconds = _coerce_positive_int(parsed.get("summary_timeout_seconds"), 90)
        agent_denies: dict[str, tuple[str, ...]] = {}
        for section_path, values in self.sections.items():
            agent_name = _child_of(section_path, "agent")
            if agent_name is None:
                continue
            deny_paths = _coerce_str_tuple(values.get("deny"))
            if deny_paths:
                agent_denies[agent_name] = deny_paths
        return CollectConfig(
            summary_concurrency=concurrency,
            summary_timeout_seconds=timeout_seconds,
            agent_denies=agent_denies,
        )

    def logging_config(self) -> LoggingConfig:
        default_path = _default_log_path_for_config(self.path)
        parsed = self.sections.get(("logging",), {})
        enabled = _parse_bool(parsed.get("enabled", "true"), True)
        raw_path = parsed.get("path")
        if isinstance(raw_path, str) and raw_path.strip():
            return LoggingConfig(enabled=enabled, path=Path(raw_path).expanduser())
        return LoggingConfig(enabled=enabled, path=default_path)

    def export_config(self) -> ExportConfig:
        parsed = self.sections.get(("export",), {})
        raw_output = parsed.get("output", "")
        if isinstance(raw_output, str):
            return ExportConfig(output=raw_output.strip())
        return ExportConfig()

    def shortcuts_config(self) -> dict[str, ShortcutConfig]:
        shortcuts: dict[str, ShortcutConfig] = {}
        for section_path, values in self.sections.items():
            shortcut_name = _child_of(section_path, "shortcut")
            if shortcut_name is None:
                continue
            params = _coerce_str_tuple(values.get("params"))
            args = _coerce_str_tuple(values.get("args"))
            if params is None or not args:
                continue
            shortcuts[shortcut_name] = ShortcutConfig(params=params, args=args)
        return shortcuts


DEFAULT_COLLECT_SUMMARY_CONCURRENCY = 4
PRIVATE_CONFIG_MODE = PRIVATE_FILE_MODE


def get_default_log_path(
    *,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    is_windows: bool | None = None,
) -> Path:
    """Return default collect log file path under the config directory."""
    return get_config_path(home=home, environ=environ, is_windows=is_windows).parent / "logs" / "collect.log"


def _default_log_path_for_config(config_path: Path) -> Path:
    return config_path.parent / "logs" / "collect.log"


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


def _parse_toml_string_array(value: str) -> tuple[str, ...] | None:
    normalized = value.strip()
    if not (normalized.startswith("[") and normalized.endswith("]")):
        return None

    body = normalized[1:-1].strip()
    if not body:
        return ()
    if body.endswith(","):
        body = body[:-1].rstrip()
    if not body:
        return ()

    items: list[str] = []
    for raw_item in body.split(","):
        item = raw_item.strip()
        if not item:
            continue
        stripped = _strip_quotes(item)
        if stripped == item or not stripped:
            return None
        items.append(stripped)
    return tuple(items)


def _parse_toml_value(value: str) -> str | tuple[str, ...]:
    array_value = _parse_toml_string_array(value)
    if array_value is not None:
        return array_value
    return _strip_quotes(value)


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def _coerce_positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value > 0 else default
    if isinstance(value, str) and value.strip():
        try:
            parsed = int(value)
        except ValueError:
            return default
        if parsed > 0:
            return parsed
    return default


def _coerce_str_tuple(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return None


def _split_section_header(header: str) -> tuple[str, ...]:
    """Split a table header into segments, keeping quoted segments whole.

    宽松 parser 只在标准解析器失败时兜底，但它产出的结构必须和标准路径一致：
    ["plugin.with.dot"] 是一个含点的 key，按 "." 无脑拆会变成三层表。
    """
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in header:
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ('"', "'"):
            quote = char
            continue
        if char == ".":
            segments.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    segments.append("".join(current).strip())
    return tuple(segment for segment in segments if segment)


def _parse_simple_toml_sections(text: str) -> dict[tuple[str, ...], dict[str, Any]]:
    """Parse minimal TOML sections without third-party deps."""
    current_section: tuple[str, ...] = ()
    parsed: dict[tuple[str, ...], dict[str, Any]] = {}
    pending_array_key: str | None = None
    pending_array_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if pending_array_key is not None:
            pending_array_lines.append(line.split("#", 1)[0].strip())
            if "]" not in line:
                continue
            parsed.setdefault(current_section, {})[pending_array_key] = _parse_toml_value(" ".join(pending_array_lines))
            pending_array_key = None
            pending_array_lines = []
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = _split_section_header(line[1:-1].strip())
            parsed.setdefault(current_section, {})
            continue

        key, sep, value = line.partition("=")
        if not sep:
            continue

        normalized_key = key.strip()
        normalized_value = value.split("#", 1)[0].strip()
        if normalized_value.startswith("[") and "]" not in normalized_value:
            pending_array_key = normalized_key
            pending_array_lines = [normalized_value]
            continue
        parsed.setdefault(current_section, {})[normalized_key] = _parse_toml_value(normalized_value)

    return parsed


def _collect_toml_sections(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], dict[str, Any]]:
    """Collect nested TOML tables keyed by their full segment path."""
    sections: dict[tuple[str, ...], dict[str, Any]] = {}
    leaves = {key: value for key, value in data.items() if not isinstance(value, dict)}
    children = {key: value for key, value in data.items() if isinstance(value, dict)}
    # 空表也要作为事实留在快照里：`[empty]` 既没有叶子也没有子表，只按叶子保存会让它
    # 在写回时整段消失。根表例外——没有 [] 这种 header，空根表不该渲染出任何东西。
    if leaves or (prefix and not children):
        sections[prefix] = leaves
    for key, value in children.items():
        sections.update(_collect_toml_sections(value, (*prefix, key)))
    return sections


def _child_of(section_path: tuple[str, ...], parent: str) -> str | None:
    """Return the child segment of a two-level `[parent.child]` table, or None."""
    if len(section_path) != 2 or section_path[0] != parent:
        return None
    return section_path[1].strip() or None


def _read_config_sections(
    config_path: Path,
) -> tuple[dict[tuple[str, ...], dict[str, Any]], ConfigurationParseMode]:
    text = config_path.read_text(encoding="utf-8")
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        # 旧版本写出的配置可能不是合法 TOML（如未转义的 Windows 路径），降级用宽松解析器读取
        return _parse_simple_toml_sections(text), ConfigurationParseMode.LEGACY
    return _collect_toml_sections(parsed), ConfigurationParseMode.TOML


def load_config_document(path: Path | None = None) -> ConfigurationDocument:
    """Read one complete configuration snapshot."""
    config_path = path if path is not None else get_config_path()
    if not config_path.exists():
        return ConfigurationDocument(path=config_path, sections={})
    sections, parse_mode = _read_config_sections(config_path)
    return ConfigurationDocument(
        path=config_path,
        sections=sections,
        parse_mode=parse_mode,
    )


def load_ai_config(path: Path | None = None) -> AIConfig | None:
    """Load AI config if file exists and parseable."""
    return load_config_document(path).ai_config()


def load_collect_config(path: Path | None = None) -> CollectConfig:
    """Load collect config with defaults for missing or invalid values."""
    return load_config_document(path).collect_config()


def load_logging_config(path: Path | None = None) -> LoggingConfig:
    """Load logging config with defaults for missing or invalid values."""
    return load_config_document(path).logging_config()


def load_export_config(path: Path | None = None) -> ExportConfig:
    """Load export config with defaults for missing or invalid values."""
    return load_config_document(path).export_config()


def load_shortcuts_config(path: Path | None = None) -> dict[str, ShortcutConfig]:
    """Load configured shortcut presets."""
    return load_config_document(path).shortcuts_config()


SUPPORTED_AI_URL_SCHEMES = frozenset({"http", "https"})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def is_loopback_host(host: str) -> bool:
    """Whether a hostname refers to this machine."""
    return host.strip().lower().strip("[]") in {h.strip("[]") for h in _LOOPBACK_HOSTS}


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

    if config.base_url:
        parsed = urlsplit(config.base_url)
        scheme = parsed.scheme.lower()
        if scheme not in SUPPORTED_AI_URL_SCHEMES:
            # 未加白名单前 file:// / ftp:// 之类的值也能走到 urllib 的 opener
            errors.append("base_url_scheme")
        elif scheme == "http" and config.api_key and not is_loopback_host(parsed.hostname or ""):
            # 明文发 API key 只在指向本机网关时才是可接受的取舍
            errors.append("base_url_plaintext_key")

    return len(errors) == 0, errors


def _toml_string(value: str) -> str:
    # json.dumps 的字符串转义规则是 TOML 基本字符串的子集，可直接复用
    return json.dumps(value, ensure_ascii=False)


_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(value: str) -> str:
    return value if _BARE_TOML_KEY.fullmatch(value) else _toml_string(value)


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(f"{_toml_key(str(key))} = {_toml_value(item)}" for key, item in value.items())
        return "{ " + items + " }"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def _render_config_sections(sections: dict[tuple[str, ...], dict[str, Any]]) -> str:
    rendered_sections: list[str] = []
    root_values = sections.get((), {})
    if root_values:
        rendered_sections.append(
            "\n".join(f"{_toml_key(key)} = {_toml_value(value)}" for key, value in root_values.items())
        )

    for section_path, values in sections.items():
        if not section_path:
            continue
        # 逐 segment 引用；先拼成一个字符串再按 "." 拆，就等于对结构做猜测
        section_header = ".".join(_toml_key(segment) for segment in section_path)
        lines = [f"[{section_header}]"]
        lines.extend(f"{_toml_key(key)} = {_toml_value(value)}" for key, value in values.items())
        rendered_sections.append("\n".join(lines))

    content = "\n\n".join(rendered_sections).rstrip()
    return f"{content}\n" if content else ""


def _replace_known_values(
    sections: dict[tuple[str, ...], dict[str, Any]],
    section_path: tuple[str, ...],
    *,
    known_keys: frozenset[str],
    values: dict[str, Any] | None,
) -> None:
    section = sections.setdefault(section_path, {})
    for key in known_keys:
        section.pop(key, None)
    if values is not None:
        section.update(values)
    if not section:
        sections.pop(section_path, None)


def write_config(
    ai_config: AIConfig | None,
    export_config: ExportConfig | None = None,
    path: Path | None = None,
    *,
    document: ConfigurationDocument | None = None,
) -> Path:
    """Update known config keys while preserving the complete document."""
    config_path = path if path is not None else get_config_path()
    snapshot = document if document is not None else load_config_document(config_path)
    if snapshot.parse_mode is ConfigurationParseMode.LEGACY:
        raise ValueError("cannot safely update a configuration parsed with the legacy fallback")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    sections = deepcopy(snapshot.sections)
    _replace_known_values(
        sections,
        ("ai",),
        known_keys=frozenset({"provider", "base_url", "model", "api_key"}),
        values=(
            {
                "provider": ai_config.provider,
                "base_url": ai_config.base_url,
                "model": ai_config.model,
                "api_key": ai_config.api_key,
            }
            if ai_config is not None
            else None
        ),
    )
    if export_config is not None:
        _replace_known_values(
            sections,
            ("export",),
            known_keys=frozenset({"output"}),
            values={"output": export_config.output},
        )

    rendered_content = _render_config_sections(sections)
    write_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with os.fdopen(os.open(config_path, write_flags, PRIVATE_CONFIG_MODE), "w", encoding="utf-8") as config_file:
        config_path.chmod(PRIVATE_CONFIG_MODE)
        config_file.write(rendered_content)
    return config_path


def write_ai_config(config: AIConfig, path: Path | None = None) -> Path:
    """Persist AI config to TOML file."""
    return write_config(config, path=path)
