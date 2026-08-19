"""Structured diagnostic errors for CLI-facing failures."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent_dump.i18n import Keys, i18n
from agent_dump.text_safety import safe_display_text


@dataclass(frozen=True)
class ParsedUri:
    """Normalized URI evidence shown in diagnostics."""

    raw: str
    scheme: str | None = None
    session_id: str | None = None


@dataclass
class DiagnosticError(Exception):
    """Stable, user-facing diagnostic payload."""

    summary: str
    details: tuple[str, ...] = ()
    searched_roots: tuple[str, ...] = ()
    parsed_uri: ParsedUri | None = None
    capability_gap: str | None = None
    next_steps: tuple[str, ...] = ()
    code: str = field(default="diagnostic")

    def __str__(self) -> str:
        return self.summary


@dataclass
class DiagnosticFileNotFoundError(DiagnosticError, FileNotFoundError):
    """Diagnostic error compatible with FileNotFoundError."""


@dataclass
class DiagnosticCapabilityError(DiagnosticError, NotImplementedError):
    """Diagnostic error compatible with NotImplementedError."""


@dataclass
class DiagnosticUsageError(DiagnosticError, ValueError):
    """Diagnostic error compatible with ValueError."""


def invalid_query_or_uri(
    summary: str,
    *,
    details: list[str] | tuple[str, ...] = (),
    parsed_uri: ParsedUri | None = None,
    next_steps: list[str] | tuple[str, ...] = (),
) -> DiagnosticError:
    return DiagnosticUsageError(
        code="invalid_query_or_uri",
        summary=summary,
        details=tuple(details),
        parsed_uri=parsed_uri,
        next_steps=tuple(next_steps),
    )


def root_not_found(
    summary: str,
    *,
    details: list[str] | tuple[str, ...] = (),
    searched_roots: list[str] | tuple[str, ...] = (),
    next_steps: list[str] | tuple[str, ...] = (),
) -> DiagnosticError:
    return DiagnosticFileNotFoundError(
        code="root_not_found",
        summary=summary,
        details=tuple(details),
        searched_roots=tuple(searched_roots),
        next_steps=tuple(next_steps),
    )


def session_not_found(
    *,
    raw_uri: str,
    scheme: str,
    session_id: str,
    searched_roots: list[str] | tuple[str, ...] = (),
    details: list[str] | tuple[str, ...] = (),
    next_steps: list[str] | tuple[str, ...] = (),
) -> DiagnosticError:
    return DiagnosticFileNotFoundError(
        code="session_not_found",
        summary=i18n.t(Keys.DIAG_SESSION_NOT_FOUND),
        details=tuple(details),
        searched_roots=tuple(searched_roots),
        parsed_uri=ParsedUri(raw=raw_uri, scheme=scheme, session_id=session_id),
        next_steps=tuple(next_steps),
    )


def unsupported_capability(
    summary: str,
    *,
    capability_gap: str,
    details: list[str] | tuple[str, ...] = (),
    parsed_uri: ParsedUri | None = None,
    next_steps: list[str] | tuple[str, ...] = (),
) -> DiagnosticError:
    return DiagnosticCapabilityError(
        code="unsupported_capability",
        summary=summary,
        details=tuple(details),
        parsed_uri=parsed_uri,
        capability_gap=capability_gap,
        next_steps=tuple(next_steps),
    )


def source_missing(
    summary: str,
    *,
    missing_path: Path | str,
    searched_roots: list[str] | tuple[str, ...] = (),
    details: list[str] | tuple[str, ...] = (),
    next_steps: list[str] | tuple[str, ...] = (),
) -> DiagnosticError:
    return DiagnosticFileNotFoundError(
        code="source_missing",
        summary=summary,
        details=(f"missing path: {missing_path}", *tuple(details)),
        searched_roots=tuple(searched_roots),
        next_steps=tuple(next_steps),
    )


def unexpected_failure(exc: BaseException) -> DiagnosticError:
    """Wrap an unanticipated exception so the CLI reports it as a diagnostic."""
    return DiagnosticError(
        code="unexpected_failure",
        summary=i18n.t(Keys.DIAG_UNEXPECTED_FAILURE),
        details=(f"{type(exc).__name__}: {exc}",),
        next_steps=(
            i18n.t(Keys.DIAG_STEP_RETRY_ONCE),
            i18n.t(Keys.DIAG_STEP_FILE_ISSUE),
        ),
    )


def render_diagnostic(error: DiagnosticError, *, t: Callable[[str], str]) -> str:
    """Render one diagnostic block with stable field labels.

    每个动态字段单独净化成一行：URI、路径、异常文本都来自第三方会话、环境路径或
    远端响应，其中的 CR/ESC 足以改写已打印的行或伪造出一整块假诊断。i18n 标签是
    静态文案，不参与净化。
    """
    lines = [t(Keys.DIAGNOSTIC_HEADER), f"{t(Keys.DIAGNOSTIC_SUMMARY)}: {safe_display_text(error.summary)}"]

    if error.parsed_uri is not None:
        lines.append(f"{t(Keys.DIAGNOSTIC_PARSED_URI)}: {safe_display_text(error.parsed_uri.raw)}")
        if error.parsed_uri.scheme:
            lines.append(f"  - scheme: {safe_display_text(error.parsed_uri.scheme)}")
        if error.parsed_uri.session_id:
            lines.append(f"  - session_id: {safe_display_text(error.parsed_uri.session_id)}")

    if error.details:
        lines.append(f"{t(Keys.DIAGNOSTIC_DETAILS)}:")
        lines.extend(f"  - {safe_display_text(detail)}" for detail in error.details if detail)

    if error.searched_roots:
        lines.append(f"{t(Keys.DIAGNOSTIC_SEARCHED_ROOTS)}:")
        lines.extend(f"  - {safe_display_text(root)}" for root in error.searched_roots if root)

    if error.capability_gap:
        lines.append(f"{t(Keys.DIAGNOSTIC_CAPABILITY_GAP)}: {safe_display_text(error.capability_gap)}")

    if error.next_steps:
        lines.append(f"{t(Keys.DIAGNOSTIC_NEXT_STEPS)}:")
        lines.extend(f"  - {safe_display_text(step)}" for step in error.next_steps if step)

    return "\n".join(lines)
