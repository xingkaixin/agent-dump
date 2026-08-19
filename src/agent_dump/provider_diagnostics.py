"""Structured diagnostics emitted while reading provider-owned data."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import sys
from threading import Lock
from typing import Any

from agent_dump.i18n import i18n
from agent_dump.text_safety import safe_display_text


@dataclass(frozen=True)
class ProviderDiagnostic:
    """One recoverable provider warning without presentation side effects."""

    message_key: str
    fields: Mapping[str, Any]


ProviderDiagnosticSink = Callable[[ProviderDiagnostic], None]
_TERMINAL_DIAGNOSTIC_LOCK = Lock()


def render_provider_diagnostic(diagnostic: ProviderDiagnostic) -> str:
    """Render one provider warning for terminal display."""
    return safe_display_text(i18n.t(diagnostic.message_key, **diagnostic.fields))


def print_provider_diagnostic(diagnostic: ProviderDiagnostic) -> None:
    """Write one provider warning to stderr without interleaving concurrent lines."""
    message = render_provider_diagnostic(diagnostic)
    with _TERMINAL_DIAGNOSTIC_LOCK:
        print(message, file=sys.stderr)
