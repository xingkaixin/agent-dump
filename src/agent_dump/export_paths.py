"""Safe output path construction for session exports."""

from hashlib import sha256
from pathlib import Path, PurePosixPath
import re

from agent_dump.diagnostics import DiagnosticError, unsupported_capability
from agent_dump.i18n import Keys, i18n
from agent_dump.text_safety import has_unsafe_line_characters

_MAX_PORTABLE_SESSION_ID_LENGTH = 120
_PORTABLE_SESSION_ID = re.compile(r"[a-z0-9_-](?:[a-z0-9._-]*[a-z0-9_-])?\Z")
_WINDOWS_RESERVED_STEMS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _unsafe_session_id_error(session_id: str, reason: str) -> DiagnosticError:
    return unsupported_capability(
        "session id cannot be used as an export filename",
        capability_gap="session id does not produce a safe filename",
        details=(f"session id: {session_id!r}", f"reason: {reason}"),
        next_steps=(i18n.t(Keys.DIAG_STEP_PICK_ANOTHER_SESSION),),
    )


def safe_session_filename(session_id: str) -> str:
    """Return one filename component derived from an untrusted session id."""
    filename = PurePosixPath(session_id.replace("\\", "/")).name
    if filename in {"", ".", ".."}:
        raise _unsafe_session_id_error(session_id, "no usable filename component")
    if has_unsafe_line_characters(filename):
        # 之前只拦 NUL，于是 CR/LF/ESC 能存活进文件名，而该文件名随后会被回显到终端
        raise _unsafe_session_id_error(session_id, "filename contains a control character")
    return filename


def identity_safe_session_filename(session_id: str) -> str:
    """Return a portable filename stem that preserves the complete session identity."""
    filename = safe_session_filename(session_id)
    is_portable = (
        session_id == filename
        and len(filename) <= _MAX_PORTABLE_SESSION_ID_LENGTH
        and _PORTABLE_SESSION_ID.fullmatch(filename) is not None
        and filename.split(".", 1)[0] not in _WINDOWS_RESERVED_STEMS
    )
    if is_portable:
        return filename

    digest = sha256(session_id.encode("utf-8")).hexdigest()
    return f"~{digest}"


def build_session_output_path(output_dir: Path, session_id: str, suffix: str) -> Path:
    """Build an export path that remains inside output_dir."""
    output_root = output_dir.resolve()
    output_path = output_dir / f"{identity_safe_session_filename(session_id)}{suffix}"
    if not output_path.resolve().is_relative_to(output_root):
        raise _unsafe_session_id_error(session_id, "resolved path escapes the output directory")
    return output_path
