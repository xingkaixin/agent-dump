"""Unified session export execution."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeAlias
import unicodedata

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.output_formats import FileOutputFormat
from agent_dump.private_files import ensure_output_dir
from agent_dump.rendering import export_session_in_format, get_session_export_path


@dataclass(frozen=True)
class ExportSuccess:
    session: Session
    output_format: FileOutputFormat
    output_path: Path


@dataclass(frozen=True)
class ExportFailure:
    session: Session
    output_format: FileOutputFormat
    error: Exception


ExportAttempt: TypeAlias = ExportSuccess | ExportFailure


class ExportRunStatus(Enum):
    EMPTY = "empty"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"

    @property
    def has_success(self) -> bool:
        return self in {ExportRunStatus.SUCCEEDED, ExportRunStatus.PARTIAL}


@dataclass(frozen=True)
class ExportRunResult:
    attempts: tuple[ExportAttempt, ...]

    @property
    def exported_paths(self) -> tuple[Path, ...]:
        return tuple(attempt.output_path for attempt in self.attempts if isinstance(attempt, ExportSuccess))

    @property
    def status(self) -> ExportRunStatus:
        success_count = sum(isinstance(attempt, ExportSuccess) for attempt in self.attempts)
        if not self.attempts:
            return ExportRunStatus.EMPTY
        if success_count == len(self.attempts):
            return ExportRunStatus.SUCCEEDED
        if success_count:
            return ExportRunStatus.PARTIAL
        return ExportRunStatus.FAILED

    def __len__(self) -> int:
        return len(self.exported_paths)


class ExportPathCollisionError(RuntimeError):
    """Raised when multiple exports would write the same portable path."""


@dataclass(frozen=True)
class _ReadyExport:
    session: Session
    output_format: FileOutputFormat
    output_dir: Path
    output_path: Path


@dataclass(frozen=True)
class _RejectedExport:
    session: Session
    output_format: FileOutputFormat
    error: Exception


_PlannedExport: TypeAlias = _ReadyExport | _RejectedExport


def _portable_path_key(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path.resolve())).casefold()


def _plan_exports(
    agent: BaseAgent,
    sessions: Sequence[Session],
    formats: Sequence[FileOutputFormat],
    output_dir_for_format: Callable[[FileOutputFormat], Path],
) -> tuple[_PlannedExport, ...]:
    plans: list[_PlannedExport] = []
    target_indices: dict[str, list[int]] = {}

    for session in sessions:
        for output_format in formats:
            try:
                output_dir = output_dir_for_format(output_format)
                output_path = get_session_export_path(agent, session, output_dir, output_format)
                target_indices.setdefault(_portable_path_key(output_path), []).append(len(plans))
                plans.append(_ReadyExport(session, output_format, output_dir, output_path))
            except Exception as exc:
                plans.append(_RejectedExport(session, output_format, exc))

    collision_indices = {index for indices in target_indices.values() if len(indices) > 1 for index in indices}
    for index in collision_indices:
        plan = plans[index]
        if isinstance(plan, _RejectedExport):
            continue
        plans[index] = _RejectedExport(
            session=plan.session,
            output_format=plan.output_format,
            error=ExportPathCollisionError(f"multiple exports resolve to the same output path: {plan.output_path}"),
        )

    return tuple(plans)


def execute_exports(
    agent: BaseAgent,
    sessions: Sequence[Session],
    formats: Sequence[FileOutputFormat],
    output_dir_for_format: Callable[[FileOutputFormat], Path],
    *,
    prepared_session_data: Mapping[str, Mapping[str, Any]] | None = None,
    session_uris: Mapping[str, str] | None = None,
    summaries: Mapping[str, str] | None = None,
) -> ExportRunResult:
    """Execute every requested file export and retain each observable outcome."""
    attempts: list[ExportAttempt] = []
    loaded_session_data: dict[str, Mapping[str, Any]] = dict(prepared_session_data or {})

    for plan in _plan_exports(agent, sessions, formats, output_dir_for_format):
        if isinstance(plan, _RejectedExport):
            attempts.append(ExportFailure(plan.session, plan.output_format, plan.error))
            continue
        try:
            output_dir = ensure_output_dir(plan.output_dir)
            if plan.output_format == "markdown" and plan.session.id not in loaded_session_data:
                loaded_session_data[plan.session.id] = agent.get_cached_session_data(plan.session)

            output_path = export_session_in_format(
                agent,
                plan.session,
                output_dir,
                plan.output_format,
                session_data=loaded_session_data.get(plan.session.id),
                session_uri=session_uris.get(plan.session.id) if session_uris is not None else None,
                json_fields=(
                    {"summary": summaries[plan.session.id]}
                    if plan.output_format == "json" and summaries is not None and plan.session.id in summaries
                    else None
                ),
            )
            attempts.append(ExportSuccess(plan.session, plan.output_format, output_path))
        except Exception as exc:
            attempts.append(ExportFailure(plan.session, plan.output_format, exc))

    return ExportRunResult(tuple(attempts))
