"""Safe output path construction for session exports."""

from pathlib import Path, PurePosixPath

from agent_dump.diagnostics import DiagnosticError, unsupported_capability


def _unsafe_session_id_error(session_id: str, reason: str) -> DiagnosticError:
    return unsupported_capability(
        "session id cannot be used as an export filename",
        capability_gap="session id does not produce a safe filename",
        details=(f"session id: {session_id!r}", f"reason: {reason}"),
        next_steps=("选择其他会话，或修复 provider 数据中的 session id。",),
    )


def safe_session_filename(session_id: str) -> str:
    """Return one filename component derived from an untrusted session id."""
    filename = PurePosixPath(session_id.replace("\\", "/")).name
    if filename in {"", ".", ".."}:
        raise _unsafe_session_id_error(session_id, "no usable filename component")
    if "\0" in filename:
        raise _unsafe_session_id_error(session_id, "filename contains a null byte")
    return filename


def build_session_output_path(output_dir: Path, session_id: str, suffix: str) -> Path:
    """Build an export path that remains inside output_dir."""
    output_root = output_dir.resolve()
    output_path = output_dir / f"{safe_session_filename(session_id)}{suffix}"
    if not output_path.resolve().is_relative_to(output_root):
        raise _unsafe_session_id_error(session_id, "resolved path escapes the output directory")
    return output_path
