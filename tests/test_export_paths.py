from pathlib import Path

import pytest

from agent_dump.diagnostics import DiagnosticCapabilityError
from agent_dump.export_paths import build_session_output_path, identity_safe_session_filename, safe_session_filename


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("session-001", "session-001"),
        ("../../../tmp/evil", "evil"),
        ("/etc/passwd", "passwd"),
        (r"C:\Users\Kevin\session", "session"),
        ("~/.zshrc", ".zshrc"),
    ],
)
def test_safe_session_filename_uses_one_path_component(session_id: str, expected: str) -> None:
    assert safe_session_filename(session_id) == expected


@pytest.mark.parametrize("session_id", ["", ".", "..", "/", "\\", "bad\0id"])
def test_safe_session_filename_rejects_unusable_ids(session_id: str) -> None:
    with pytest.raises(DiagnosticCapabilityError) as exc_info:
        safe_session_filename(session_id)

    assert exc_info.value.code == "unsupported_capability"


def test_build_session_output_path_keeps_untrusted_id_inside_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"

    result = build_session_output_path(output_dir, str(tmp_path / "escaped"), ".json")

    assert result.parent == output_dir
    assert result.name.startswith("~")
    assert result.suffix == ".json"
    assert result.resolve().is_relative_to(output_dir.resolve())


def test_identity_safe_filename_preserves_portable_ids() -> None:
    assert identity_safe_session_filename("session-001") == "session-001"


def test_identity_safe_filename_distinguishes_path_shaped_ids() -> None:
    first = identity_safe_session_filename("project-a/shared")
    second = identity_safe_session_filename("project-b/shared")

    assert first != second
    assert first.startswith("~")
    assert second.startswith("~")
    assert first == identity_safe_session_filename("project-a/shared")


def test_identity_safe_filename_avoids_case_insensitive_collisions() -> None:
    upper = identity_safe_session_filename("Case")
    lower = identity_safe_session_filename("case")

    assert upper.casefold() != lower.casefold()


def test_build_session_output_path_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    outside_path = tmp_path / "outside.json"
    outside_path.write_text("outside", encoding="utf-8")
    output_path = output_dir / "session.json"
    try:
        output_path.symlink_to(outside_path)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(DiagnosticCapabilityError):
        build_session_output_path(output_dir, "session", ".json")
