"""Unified session export execution."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import unicodedata

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.private_files import ensure_output_dir
from agent_dump.rendering import export_session_in_format, get_session_export_path


@dataclass(frozen=True)
class ExportAttempt:
    session: Session
    output_format: str
    output_path: Path | None
    error: Exception | None

    def __post_init__(self) -> None:
        if (self.output_path is None) == (self.error is None):
            raise ValueError("an export attempt must contain exactly one of output_path or error")

    @property
    def succeeded(self) -> bool:
        return self.error is None


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


class ExportPathCollisionError(RuntimeError):
    """Raised when multiple exports would write the same portable path."""


@dataclass(frozen=True)
class _PlannedExport:
    session: Session
    output_format: str
    output_dir: Path | None
    output_path: Path | None
    error: Exception | None


def _portable_path_key(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path.resolve())).casefold()


def _plan_exports(
    agent: BaseAgent,
    sessions: Sequence[Session],
    formats: Sequence[str],
    output_dir_for_format: Callable[[str], Path],
) -> tuple[_PlannedExport, ...]:
    plans: list[_PlannedExport] = []
    target_indices: dict[str, list[int]] = {}

    for session in sessions:
        for output_format in formats:
            try:
                output_dir = output_dir_for_format(output_format)
                output_path = get_session_export_path(agent, session, output_dir, output_format)
                target_indices.setdefault(_portable_path_key(output_path), []).append(len(plans))
                plans.append(_PlannedExport(session, output_format, output_dir, output_path, None))
            except Exception as exc:
                plans.append(_PlannedExport(session, output_format, None, None, exc))

    collision_indices = {index for indices in target_indices.values() if len(indices) > 1 for index in indices}
    for index in collision_indices:
        plan = plans[index]
        plans[index] = _PlannedExport(
            session=plan.session,
            output_format=plan.output_format,
            output_dir=plan.output_dir,
            output_path=plan.output_path,
            error=ExportPathCollisionError(f"multiple exports resolve to the same output path: {plan.output_path}"),
        )

    return tuple(plans)


def execute_exports(
    agent: BaseAgent,
    sessions: Sequence[Session],
    formats: Sequence[str],
    output_dir_for_format: Callable[[str], Path],
    *,
    prepared_session_data: Mapping[str, Mapping[str, Any]] | None = None,
    session_uris: Mapping[str, str] | None = None,
    summaries: Mapping[str, str] | None = None,
) -> ExportRunResult:
    """Execute every requested file export and retain each observable outcome."""
    attempts: list[ExportAttempt] = []
    loaded_session_data: dict[str, Mapping[str, Any]] = dict(prepared_session_data or {})

    for plan in _plan_exports(agent, sessions, formats, output_dir_for_format):
        output_path: Path | None = None
        error = plan.error
        if error is None and plan.output_dir is not None:
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
            except Exception as exc:
                error = exc

        attempts.append(
            ExportAttempt(
                session=plan.session,
                output_format=plan.output_format,
                output_path=output_path,
                error=error,
            )
        )

    return ExportRunResult(tuple(attempts))
