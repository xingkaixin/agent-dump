"""Collect mode workflow orchestration."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import sys
import threading
from typing import Protocol

from agent_dump.collect_dates import CollectDateError, CollectDateErrorCode, resolve_collect_date_range
from agent_dump.collect_handoff import build_collect_handoff_prompt
from agent_dump.collect_logging import CollectLogger, create_collect_logger
from agent_dump.collect_models import (
    CollectAction,
    CollectFailurePhase,
    CollectOverviewProgress,
    CollectProgressEvent,
    CollectRunStats,
    CollectStage,
    CollectStartProgress,
    MergeSessionsProgress,
    PlanChunksProgress,
    PlannedCollectEntry,
    RenderFinalProgress,
    ScanSessionsProgress,
    SummarizeChunksProgress,
    TreeReductionProgress,
    WriteOutputProgress,
)
from agent_dump.collect_output import write_collect_markdown
from agent_dump.collect_progress import (
    build_collect_run_stats,
    emit_collect_progress,
)
from agent_dump.collect_prompts import build_collect_final_prompt
from agent_dump.collect_reduction import reduce_collect_summaries, summarize_collect_entries
from agent_dump.collect_requests import (
    StructuredSummaryRequester,
    request_structured_summary_from_llm,
    request_summary_from_llm,
)
from agent_dump.collect_sessions import (
    collect_entries_with_status,
    collect_scan_days,
    plan_collect_entries,
    select_collect_sessions,
)
from agent_dump.command_plan import CollectOperation
from agent_dump.config import (
    AIConfig,
    AIConfigError,
    CollectConfig,
    ConfigurationDocument,
    load_config_document,
    validate_ai_config,
)
from agent_dump.diagnostics import print_recoverable_diagnostic
from agent_dump.i18n import Keys, i18n
from agent_dump.scanner import AgentScanner
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import safe_body_text, safe_display_text
from agent_dump.time_utils import get_local_timezone


def _collect_default_filename(*, since_date: date, until_date: date) -> str:
    return f"agent-dump-collect-{since_date.strftime('%Y%m%d')}-{until_date.strftime('%Y%m%d')}.md"


def resolve_collect_save_path(save: str | None, *, since_date: date, until_date: date) -> Path | None:
    """Resolve collect output path from an optional save spec."""
    if save is None:
        return None

    candidate = Path(save)
    default_name = _collect_default_filename(since_date=since_date, until_date=until_date)

    if candidate.exists():
        return candidate / default_name if candidate.is_dir() else candidate
    if candidate.suffix.lower() == ".md":
        return candidate
    return candidate / default_name


def preview_collect_save_path(save: str | None, *, since_date: date, until_date: date) -> Path:
    resolved = resolve_collect_save_path(save, since_date=since_date, until_date=until_date)
    if resolved is not None:
        return resolved
    return Path.cwd() / _collect_default_filename(since_date=since_date, until_date=until_date)


def _report_collect_log_write_error(path: Path, error: OSError) -> None:
    print(
        render_terminal_message(Keys.COLLECT_LOG_WRITE_FAILED, path=path, error=error),
        file=sys.stderr,
    )


def _format_collect_progress(event: CollectProgressEvent) -> str:
    """Format one collect progress event for stderr."""
    if isinstance(event, CollectStartProgress):
        return i18n.t(Keys.COLLECT_PROGRESS_START, since=event.since, until=event.until)
    if isinstance(event, CollectOverviewProgress):
        breakdown = ", ".join(f"{agent_name} {count}" for agent_name, count in event.agent_session_counts.items())
        overview = i18n.t(
            Keys.COLLECT_PROGRESS_OVERVIEW,
            session_count=event.session_count,
            chunk_count=event.chunk_count,
            concurrency=event.concurrency,
        )
        if not breakdown:
            return overview
        return "\n".join([overview, i18n.t(Keys.COLLECT_PROGRESS_AGENT_BREAKDOWN, breakdown=breakdown)])
    if isinstance(event, ScanSessionsProgress):
        return i18n.t(Keys.COLLECT_PROGRESS_SCAN_SESSIONS, current=event.current, total=event.total)
    if isinstance(event, PlanChunksProgress):
        if event.current >= event.total:
            return i18n.t(
                Keys.COLLECT_PROGRESS_PLAN_CHUNKS_DONE,
                session_count=event.current,
                chunk_count=event.chunk_total,
            )
        return i18n.t(Keys.COLLECT_PROGRESS_PLAN_CHUNKS, current=event.current, total=event.total)
    if isinstance(event, SummarizeChunksProgress):
        return i18n.t(
            Keys.COLLECT_PROGRESS_SUMMARIZE_CHUNKS,
            current=event.current,
            total=event.total,
            concurrency=event.concurrency,
        )
    if isinstance(event, MergeSessionsProgress):
        return i18n.t(Keys.COLLECT_PROGRESS_MERGE_SESSIONS, current=event.current, total=event.total)
    if isinstance(event, TreeReductionProgress):
        return i18n.t(
            Keys.COLLECT_PROGRESS_TREE_REDUCTION,
            level=event.level,
            current=event.current,
            total=event.total,
        )
    if isinstance(event, RenderFinalProgress):
        return i18n.t(Keys.COLLECT_PROGRESS_RENDER_FINAL, current=event.current, total=event.total)
    if isinstance(event, WriteOutputProgress):
        return i18n.t(Keys.COLLECT_PROGRESS_WRITE_OUTPUT, current=event.current, total=event.total)
    raise AssertionError(f"unsupported collect progress event: {type(event).__name__}")


@contextmanager
def show_collect_progress() -> Iterator[Callable[[CollectProgressEvent], None]]:
    """Show collect multi-stage progress on stderr."""
    is_tty = sys.stderr.isatty()
    stop_event = threading.Event()
    progress_lock = threading.Lock()
    spinner_frames = "|/-\\"
    spinner_thread: threading.Thread | None = None
    last_rendered = ""

    def _clear_tty_line(text: str) -> None:
        width = len(text) + 4
        sys.stderr.write("\r" + (" " * width) + "\r")

    def _update(event: CollectProgressEvent) -> None:
        nonlocal last_rendered
        text = safe_display_text(_format_collect_progress(event))
        if event.stage in {CollectStage.COLLECT_START, CollectStage.COLLECT_OVERVIEW}:
            if is_tty:
                with progress_lock:
                    if last_rendered:
                        _clear_tty_line(last_rendered)
                    print(text, file=sys.stderr)
            else:
                print(text, file=sys.stderr)
            return
        with progress_lock:
            last_rendered = text
        if is_tty:
            return
        print(text, file=sys.stderr)

    if is_tty:

        def _spin() -> None:
            idx = 0
            while not stop_event.wait(0.1):
                with progress_lock:
                    text = last_rendered
                    if not text:
                        continue
                    sys.stderr.write(f"\r{spinner_frames[idx % len(spinner_frames)]} {text}")
                    sys.stderr.flush()
                idx += 1

        spinner_thread = threading.Thread(target=_spin, daemon=True)
        spinner_thread.start()

    try:
        yield _update
    finally:
        if is_tty:
            stop_event.set()
            if spinner_thread is not None:
                spinner_thread.join(timeout=0.3)
        if last_rendered and is_tty:
            with progress_lock:
                _clear_tty_line(last_rendered)
                sys.stderr.write(last_rendered)
                sys.stderr.write("\n")
                sys.stderr.flush()


def _format_collect_dry_run_preview(*, run_stats: CollectRunStats, output_path: Path) -> str:
    breakdown = ", ".join(
        f"{safe_display_text(agent_name)} {count}"
        for agent_name, count in sorted(run_stats.agent_session_counts.items())
    )
    return "\n".join(
        [
            i18n.t(Keys.COLLECT_DRY_RUN_HEADER),
            render_terminal_message(Keys.COLLECT_DRY_RUN_DATE_RANGE, since=run_stats.since, until=run_stats.until),
            render_terminal_message(Keys.COLLECT_DRY_RUN_PROVIDER_BREAKDOWN, breakdown=breakdown),
            render_terminal_message(Keys.COLLECT_DRY_RUN_SESSION_COUNT, count=run_stats.session_count),
            render_terminal_message(Keys.COLLECT_DRY_RUN_CHUNK_COUNT, count=run_stats.chunk_count),
            render_terminal_message(Keys.COLLECT_DRY_RUN_CONCURRENCY, concurrency=run_stats.concurrency),
            render_terminal_message(Keys.COLLECT_DRY_RUN_SAVE_PATH, path=output_path),
        ]
    )


class _SummaryRequester(Protocol):
    def __call__(self, config: AIConfig, prompt: str, *, timeout_seconds: int) -> str: ...


@dataclass(frozen=True)
class _CollectPlan:
    planned_entries: list[PlannedCollectEntry]
    run_stats: CollectRunStats
    read_failed_count: int


@dataclass(frozen=True)
class _CollectOutput:
    markdown: str
    output_path: Path
    session_count: int
    summary_failed_count: int


def _validated_collect_ai_config(config_document: ConfigurationDocument) -> AIConfig | None:
    config = config_document.ai_config()
    valid, errors = validate_ai_config(config, config_file_exists=config_document.source_exists)
    if valid and config is not None:
        return config

    if AIConfigError.MISSING_FILE in errors:
        print(i18n.t(Keys.COLLECT_CONFIG_MISSING))
    elif AIConfigError.BASE_URL_SCHEME in errors:
        print(i18n.t(Keys.COLLECT_CONFIG_BAD_SCHEME))
    elif AIConfigError.BASE_URL_PLAINTEXT_KEY in errors:
        print(i18n.t(Keys.COLLECT_CONFIG_PLAINTEXT_KEY))
    else:
        print(i18n.t(Keys.COLLECT_CONFIG_INCOMPLETE, fields=",".join(error.value for error in errors)))
    print(i18n.t(Keys.COLLECT_CONFIG_HINT))
    return None


def _log_collect_failure(logger: CollectLogger | None, phase: CollectFailurePhase, error: Exception) -> None:
    if logger is not None:
        logger.log("collect_run_fail", phase=phase.value, error=str(error))


def _prepare_collect_plan(
    operation: CollectOperation,
    *,
    scanner: AgentScanner,
    collect_config: CollectConfig,
    since_date: date,
    until_date: date,
    progress_callback: Callable[[CollectProgressEvent], None],
    logger: CollectLogger | None,
) -> _CollectPlan | None:
    try:
        emit_collect_progress(
            progress_callback,
            CollectStartProgress(since=since_date.isoformat(), until=until_date.isoformat()),
        )
        local_tz = get_local_timezone()
        session_results = scanner.get_available_sessions(collect_scan_days(since_date, local_tz))
        if not session_results:
            print(i18n.t(Keys.NO_AGENTS_FOUND))
            return None
        available_agents = [agent for agent, _ in session_results]
        read_result = collect_entries_with_status(
            session_groups=session_results,
            since_date=since_date,
            until_date=until_date,
            collect_config=collect_config,
            query_spec=operation.query_spec,
            local_tz=local_tz,
            progress_callback=progress_callback,
            diagnostic_sink=print_recoverable_diagnostic,
            logger=logger,
        )
        entries = read_result.entries
        if not entries:
            print(i18n.t(Keys.COLLECT_NO_SESSIONS, since=since_date.isoformat(), until=until_date.isoformat()))
            return None

        if logger is not None:
            logger.log(
                "collect_run_start",
                since=since_date.isoformat(),
                until=until_date.isoformat(),
                summary_concurrency=collect_config.summary_concurrency,
                agent_count=len(available_agents),
                session_count=len(entries),
            )
        planned_entries, _ = plan_collect_entries(entries, progress_callback=progress_callback)
        run_stats = build_collect_run_stats(
            entries=entries,
            planned_entries=planned_entries,
            since_date=since_date,
            until_date=until_date,
            summary_concurrency=collect_config.summary_concurrency,
        )
        emit_collect_progress(
            progress_callback,
            CollectOverviewProgress(
                session_count=run_stats.session_count,
                chunk_count=run_stats.chunk_count,
                concurrency=run_stats.concurrency,
                agent_session_counts=run_stats.agent_session_counts,
            ),
        )
    except Exception as exc:
        _log_collect_failure(logger, CollectFailurePhase.READ, exc)
        print(i18n.t(Keys.COLLECT_READ_FAILED, error=safe_display_text(str(exc))))
        return None

    return _CollectPlan(
        planned_entries=planned_entries,
        run_stats=run_stats,
        read_failed_count=read_result.failed_count,
    )


def _execute_collect_plan(
    operation: CollectOperation,
    plan: _CollectPlan,
    *,
    ai_config: AIConfig,
    collect_config: CollectConfig,
    since_date: date,
    until_date: date,
    progress_callback: Callable[[CollectProgressEvent], None],
    logger: CollectLogger,
    request_summary: _SummaryRequester,
    request_structured_summary: StructuredSummaryRequester,
) -> _CollectOutput | None:
    try:
        session_summaries = summarize_collect_entries(
            config=ai_config,
            planned_entries=plan.planned_entries,
            summary_concurrency=collect_config.summary_concurrency,
            progress_callback=progress_callback,
            timeout_seconds=collect_config.summary_timeout_seconds,
            logger=logger,
            mode=operation.collect_mode,
            request_structured_summary=request_structured_summary,
        )
    except Exception as exc:
        _log_collect_failure(logger, CollectFailurePhase.SUMMARIZE, exc)
        print(i18n.t(Keys.COLLECT_API_FAILED, error=safe_display_text(str(exc))))
        return None

    try:
        emit_collect_progress(progress_callback, RenderFinalProgress(current=0, total=2))
        aggregate = reduce_collect_summaries(
            config=ai_config,
            session_summaries=session_summaries,
            progress_callback=progress_callback,
            timeout_seconds=collect_config.summary_timeout_seconds,
            logger=logger,
            mode=operation.collect_mode,
            request_structured_summary=request_structured_summary,
        )
        emit_collect_progress(progress_callback, RenderFinalProgress(current=1, total=2))
        prompt = build_collect_final_prompt(
            since_date=since_date,
            until_date=until_date,
            aggregate=aggregate,
            has_truncated=any(entry.collect_entry.is_truncated for entry in plan.planned_entries),
            mode=operation.collect_mode,
        )
        markdown = request_summary(
            ai_config,
            prompt,
            timeout_seconds=collect_config.summary_timeout_seconds,
        )
        emit_collect_progress(progress_callback, RenderFinalProgress(current=2, total=2))
    except Exception as exc:
        _log_collect_failure(logger, CollectFailurePhase.RENDER, exc)
        print(i18n.t(Keys.COLLECT_API_FAILED, error=safe_display_text(str(exc))))
        return None

    summary_failed_count = len(plan.planned_entries) - len(session_summaries)
    if plan.read_failed_count or summary_failed_count:
        notice = i18n.t(
            Keys.COLLECT_INCOMPLETE_REPORT,
            read_failed=plan.read_failed_count,
            summary_failed=summary_failed_count,
            included=len(session_summaries),
        )
        markdown = f"> {notice}\n\n{markdown}"

    try:
        emit_collect_progress(progress_callback, WriteOutputProgress(current=0, total=1))
        output_path = write_collect_markdown(
            markdown,
            since_date=since_date,
            until_date=until_date,
            output_path=resolve_collect_save_path(
                operation.save,
                since_date=since_date,
                until_date=until_date,
            ),
        )
        emit_collect_progress(progress_callback, WriteOutputProgress(current=1, total=1))
    except Exception as exc:
        _log_collect_failure(logger, CollectFailurePhase.WRITE, exc)
        print(i18n.t(Keys.COLLECT_WRITE_FAILED, error=safe_display_text(str(exc))))
        return None

    return _CollectOutput(
        markdown=markdown,
        output_path=output_path,
        session_count=len(session_summaries),
        summary_failed_count=summary_failed_count,
    )


def _handle_collect_dry_run(
    operation: CollectOperation,
    *,
    scanner_factory: Callable[[], AgentScanner],
    collect_config: CollectConfig,
    since_date: date,
    until_date: date,
) -> int:
    scanner = scanner_factory()
    with show_collect_progress() as update_progress:
        plan = _prepare_collect_plan(
            operation,
            scanner=scanner,
            collect_config=collect_config,
            since_date=since_date,
            until_date=until_date,
            progress_callback=update_progress,
            logger=None,
        )
    if plan is None:
        return 1
    print(
        _format_collect_dry_run_preview(
            run_stats=plan.run_stats,
            output_path=preview_collect_save_path(
                operation.save,
                since_date=since_date,
                until_date=until_date,
            ),
        )
    )
    return 0


def _handle_collect_execution(
    operation: CollectOperation,
    *,
    scanner_factory: Callable[[], AgentScanner],
    request_summary: _SummaryRequester,
    request_structured_summary: StructuredSummaryRequester,
    ai_config: AIConfig,
    collect_config: CollectConfig,
    logger: CollectLogger,
    since_date: date,
    until_date: date,
) -> int:
    scanner = scanner_factory()
    with show_collect_progress() as update_progress:
        plan = _prepare_collect_plan(
            operation,
            scanner=scanner,
            collect_config=collect_config,
            since_date=since_date,
            until_date=until_date,
            progress_callback=update_progress,
            logger=logger,
        )
        if plan is None:
            return 1
        output = _execute_collect_plan(
            operation,
            plan,
            ai_config=ai_config,
            collect_config=collect_config,
            since_date=since_date,
            until_date=until_date,
            progress_callback=update_progress,
            logger=logger,
            request_summary=request_summary,
            request_structured_summary=request_structured_summary,
        )
    if output is None:
        return 1

    logger.log(
        "collect_run_finish",
        output_path=str(output.output_path),
        session_count=output.session_count,
        read_failed_count=plan.read_failed_count,
        summary_failed_count=output.summary_failed_count,
    )
    print(safe_body_text(output.markdown))
    print(render_terminal_message(Keys.COLLECT_OUTPUT_SAVED, path=output.output_path))
    return 0


def _handle_collect_prompt(
    operation: CollectOperation,
    *,
    scanner_factory: Callable[[], AgentScanner],
    collect_config: CollectConfig,
    since_date: date,
    until_date: date,
) -> int:
    try:
        local_tz = get_local_timezone()
        print(
            i18n.t(Keys.COLLECT_PROGRESS_START, since=since_date.isoformat(), until=until_date.isoformat()),
            file=sys.stderr,
        )
        scanner = scanner_factory()
        session_groups = scanner.get_available_sessions(collect_scan_days(since_date, local_tz))
        if not session_groups:
            print(i18n.t(Keys.NO_AGENTS_FOUND), file=sys.stderr)
            return 1
        selected = select_collect_sessions(
            session_groups=session_groups,
            since_date=since_date,
            until_date=until_date,
            collect_config=collect_config,
            query_spec=operation.query_spec,
            local_tz=local_tz,
            diagnostic_sink=print_recoverable_diagnostic,
        )
        if not selected:
            print(
                i18n.t(Keys.COLLECT_NO_SESSIONS, since=since_date.isoformat(), until=until_date.isoformat()),
                file=sys.stderr,
            )
            return 0
        prompt = build_collect_handoff_prompt(
            sessions=selected,
            since_date=since_date,
            until_date=until_date,
            mode=operation.collect_mode,
            output_path=preview_collect_save_path(
                operation.save, since_date=since_date, until_date=until_date
            ).resolve(),
            working_directory=Path.cwd(),
            generated_at=datetime.now(local_tz),
        )
    except Exception as exc:
        print(render_terminal_message(Keys.COLLECT_READ_FAILED, error=exc), file=sys.stderr)
        return 1
    print(prompt)
    return 0


def handle_collect_mode(
    operation: CollectOperation,
    *,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
    request_summary: _SummaryRequester = request_summary_from_llm,
    request_structured_summary: StructuredSummaryRequester = request_structured_summary_from_llm,
) -> int:
    """Handle `--collect` flow."""
    diagnostic_output = sys.stderr if operation.action is CollectAction.EMIT_PROMPT else sys.stdout
    try:
        since_date, until_date = resolve_collect_date_range(
            operation.since,
            operation.until,
            days=operation.days,
        )
    except CollectDateError as exc:
        if exc.code is CollectDateErrorCode.SINCE_AFTER_UNTIL:
            print(i18n.t(Keys.COLLECT_DATE_RANGE_INVALID), file=diagnostic_output)
        else:
            print(i18n.t(Keys.COLLECT_DATE_FORMAT_INVALID), file=diagnostic_output)
        return 1

    try:
        config_document = load_config_document()
        config_document.validate_collect_safety()
    except (OSError, ValueError) as exc:
        print(render_terminal_message(Keys.COLLECT_CONFIG_UNSAFE, field=exc), file=diagnostic_output)
        return 1
    if operation.action is CollectAction.EMIT_PROMPT:
        return _handle_collect_prompt(
            operation,
            scanner_factory=scanner_factory,
            collect_config=config_document.collect_config(),
            since_date=since_date,
            until_date=until_date,
        )
    if operation.action is CollectAction.DRY_RUN:
        return _handle_collect_dry_run(
            operation,
            scanner_factory=scanner_factory,
            collect_config=config_document.collect_config(),
            since_date=since_date,
            until_date=until_date,
        )

    ai_config = _validated_collect_ai_config(config_document)
    if ai_config is None:
        return 1
    collect_config = config_document.collect_config()
    collect_logger = create_collect_logger(
        config_document.logging_config(),
        on_write_error=_report_collect_log_write_error,
    )
    return _handle_collect_execution(
        operation,
        scanner_factory=scanner_factory,
        request_summary=request_summary,
        request_structured_summary=request_structured_summary,
        ai_config=ai_config,
        collect_config=collect_config,
        logger=collect_logger,
        since_date=since_date,
        until_date=until_date,
    )
