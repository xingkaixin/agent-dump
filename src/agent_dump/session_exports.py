"""Shared file operations for provider session exports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_dump.diagnostics import source_missing, unsupported_capability
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot
from agent_dump.private_files import copy_private_file, write_private_text

if TYPE_CHECKING:
    from agent_dump.agents.base import Session


def write_session_json(
    output_path: Path,
    payload: Mapping[str, Any],
    fields: Mapping[str, Any] | None = None,
) -> Path:
    """Write one unified JSON export with optional workflow-owned fields."""
    document = dict(payload)
    if fields:
        document.update(fields)
    return write_private_text(output_path, json.dumps(document, ensure_ascii=False, indent=2))


def copy_raw_session_file(
    session: Session,
    output_path: Path,
    search_roots: Sequence[SearchRoot],
) -> Path:
    """Copy one provider-owned raw session file to a private output path."""
    source_path = session.source_path
    if not source_path.exists():
        raise source_missing(
            "raw session source is missing",
            missing_path=source_path,
            searched_roots=[root.render() for root in search_roots],
            next_steps=(
                i18n.t(Keys.DIAG_STEP_RAW_SOURCE_LOCAL),
                i18n.t(Keys.DIAG_STEP_LIST_TO_CHECK_VISIBLE),
            ),
        )
    if not source_path.is_file():
        raise unsupported_capability(
            "raw export is not supported for this session source",
            capability_gap="session source is a directory, not a single raw file",
            details=(f"source path: {source_path}",),
            next_steps=(
                i18n.t(Keys.DIAG_STEP_USE_JSON_OR_MARKDOWN),
                i18n.t(Keys.DIAG_STEP_CHECK_PROVIDER_HAS_RAW),
            ),
        )

    return copy_private_file(source_path, output_path)
