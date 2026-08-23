"""Structured diagnostics emitted by session search operations."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import sys
from threading import Lock
from typing import Any

from agent_dump.terminal_output import render_terminal_message


@dataclass(frozen=True)
class SearchDiagnostic:
    """One recoverable search warning without presentation side effects."""

    message_key: str
    fields: Mapping[str, Any]


SearchDiagnosticSink = Callable[[SearchDiagnostic], None]
_TERMINAL_DIAGNOSTIC_LOCK = Lock()


def emit_search_diagnostic(
    sink: SearchDiagnosticSink | None,
    message_key: str,
    **fields: Any,
) -> None:
    if sink is not None:
        sink(SearchDiagnostic(message_key=message_key, fields=fields))


def print_search_diagnostic(diagnostic: SearchDiagnostic) -> None:
    message = render_terminal_message(diagnostic.message_key, **diagnostic.fields)
    with _TERMINAL_DIAGNOSTIC_LOCK:
        print(message, file=sys.stderr)
