"""Expand configured shortcut invocations into regular CLI arguments."""

from collections.abc import Mapping
from datetime import date
from enum import Enum
from pathlib import Path
from string import Formatter

from agent_dump.config import ShortcutConfig
from agent_dump.date_input import parse_date_input


class ShortcutErrorCode(str, Enum):
    MISSING_NAME = "missing_name"
    DATE_INVALID = "date_invalid"
    TEMPLATE_INVALID = "template_invalid"
    NOT_FOUND = "not_found"
    ARGS_MISMATCH = "args_mismatch"
    UNKNOWN_VARIABLE = "unknown_variable"


class ShortcutExpansionError(ValueError):
    """A typed shortcut failure with fields kept separate from presentation."""

    def __init__(
        self,
        code: ShortcutErrorCode,
        *,
        shortcut_name: str | None = None,
        expected: int | None = None,
        actual: int | None = None,
        variable_name: str | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.shortcut_name = shortcut_name
        self.expected = expected
        self.actual = actual
        self.variable_name = variable_name


def _parse_date(value: str) -> date:
    parsed_date = parse_date_input(value)
    if parsed_date is None:
        raise ShortcutExpansionError(ShortcutErrorCode.DATE_INVALID)
    return parsed_date


def _build_variables(params: tuple[str, ...], values: tuple[str, ...]) -> dict[str, str]:
    variables = dict(zip(params, values, strict=True))
    raw_date = variables.get("date")
    if raw_date is None:
        return variables

    parsed_date = _parse_date(raw_date)
    variables["date"] = parsed_date.strftime("%Y%m%d")
    variables["year"] = parsed_date.strftime("%Y")
    variables["month"] = parsed_date.strftime("%m")
    variables["year_month"] = parsed_date.strftime("%Y-%m")
    return variables


def _render_arg(template: str, variables: Mapping[str, str]) -> str:
    try:
        parts = tuple(Formatter().parse(template))
    except ValueError as error:
        raise ShortcutExpansionError(ShortcutErrorCode.TEMPLATE_INVALID) from error

    rendered: list[str] = []
    for literal_text, field_name, format_spec, conversion in parts:
        rendered.append(literal_text)
        if field_name is None:
            continue
        if format_spec or conversion:
            raise ShortcutExpansionError(ShortcutErrorCode.TEMPLATE_INVALID)
        if field_name not in variables:
            raise ShortcutExpansionError(
                ShortcutErrorCode.UNKNOWN_VARIABLE,
                variable_name=field_name,
            )
        rendered.append(variables[field_name])

    result = "".join(rendered)
    if result.startswith("~"):
        return str(Path(result).expanduser())
    return result


def expand_shortcut_argv(
    argv: list[str],
    shortcuts: Mapping[str, ShortcutConfig],
) -> list[str]:
    """Expand one shortcut invocation while preserving ordinary trailing options."""
    if "--shortcut" not in argv:
        return argv

    shortcut_index = argv.index("--shortcut")
    prefix = argv[:shortcut_index]
    suffix = argv[shortcut_index + 1 :]
    if not suffix or not suffix[0].strip():
        raise ShortcutExpansionError(ShortcutErrorCode.MISSING_NAME)

    shortcut_name = suffix[0].strip()
    value_tokens: list[str] = []
    remainder_index = len(suffix)
    for index, token in enumerate(suffix[1:], start=1):
        if token.startswith("-"):
            remainder_index = index
            break
        value_tokens.append(token)

    shortcut = shortcuts.get(shortcut_name)
    if shortcut is None:
        raise ShortcutExpansionError(
            ShortcutErrorCode.NOT_FOUND,
            shortcut_name=shortcut_name,
        )

    expected = len(shortcut.params)
    actual = len(value_tokens)
    if actual != expected:
        raise ShortcutExpansionError(
            ShortcutErrorCode.ARGS_MISMATCH,
            shortcut_name=shortcut_name,
            expected=expected,
            actual=actual,
        )

    variables = _build_variables(shortcut.params, tuple(value_tokens))
    expanded_args = [_render_arg(arg, variables) for arg in shortcut.args]
    remainder = suffix[remainder_index:]
    return prefix + expanded_args + remainder
