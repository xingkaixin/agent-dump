"""Unified session export execution."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.private_files import ensure_output_dir
from agent_dump.rendering import apply_summary_to_json_export, export_session_in_format


@dataclass(frozen=True)
class ExportAttempt:
    session: Session
    output_format: str
    output_path: Path | None
    error: Exception | None

    @property
    def succeeded(self) -> bool:
        return self.output_path is not None


@dataclass(frozen=True)
class ExportRunResult:
    attempts: tuple[ExportAttempt, ...]

    @property
    def exported_paths(self) -> tuple[Path, ...]:
        return tuple(attempt.output_path for attempt in self.attempts if attempt.output_path is not None)

    @property
    def had_success(self) -> bool:
        return any(attempt.succeeded for attempt in self.attempts)

    @property
    def all_failed(self) -> bool:
        return bool(self.attempts) and not self.had_success

    def __len__(self) -> int:
        return len(self.exported_paths)


def execute_exports(
    agent: BaseAgent,
    sessions: Sequence[Session],
    formats: Sequence[str],
    output_dir_for_format: Callable[[str], Path],
    *,
    prepared_session_data: Mapping[str, dict[str, Any]] | None = None,
    session_uris: Mapping[str, str] | None = None,
    summaries: Mapping[str, str] | None = None,
) -> ExportRunResult:
    """Execute every requested file export and retain each observable outcome."""
    attempts: list[ExportAttempt] = []
    loaded_session_data = dict(prepared_session_data or {})

    for session in sessions:
        for output_format in formats:
            output_path: Path | None = None
            error: Exception | None = None
            try:
                output_dir = ensure_output_dir(output_dir_for_format(output_format))
                if output_format == "markdown" and session.id not in loaded_session_data:
                    loaded_session_data[session.id] = agent.get_cached_session_data(session)

                output_path = export_session_in_format(
                    agent,
                    session,
                    output_dir,
                    output_format,
                    session_data=loaded_session_data.get(session.id),
                    session_uri=session_uris.get(session.id) if session_uris is not None else None,
                )
                summary = summaries.get(session.id) if summaries is not None else None
                if output_format == "json" and summary is not None:
                    try:
                        apply_summary_to_json_export(output_path, summary)
                    except Exception as exc:
                        error = exc
            except Exception as exc:
                error = exc

            attempts.append(
                ExportAttempt(
                    session=session,
                    output_format=output_format,
                    output_path=output_path,
                    error=error,
                )
            )

    return ExportRunResult(tuple(attempts))
