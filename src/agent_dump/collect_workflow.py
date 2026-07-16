"""Collect mode workflow orchestration."""

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
import sys
import threading
from typing import cast

from agent_dump.agents.base import BaseAgent
from agent_dump.collect import (
    build_collect_final_prompt,
    build_collect_run_stats,
    collect_entries,
    create_collect_logger,
    emit_collect_progress,
    plan_collect_entries,
    reduce_collect_summaries,
    request_summary_from_llm,
    resolve_collect_date_range,
    summarize_collect_entries,
    write_collect_markdown,
)
from agent_dump.collect_models import CollectProgressEvent, CollectRunStats
from agent_dump.config import (
    AIConfig,
    load_ai_config,
    load_collect_config,
    load_logging_config,
    validate_ai_config,
)
from agent_dump.i18n import Keys, i18n
from agent_dump.query_filter import QuerySpec, parse_query_uri
from agent_dump.rendering import render_session_text
from agent_dump.scanner import AgentScanner


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


def _format_collect_progress(event: CollectProgressEvent) -> str:
    """Format one collect progress event for stderr."""
    if event.stage == "collect_start":
        return i18n.t(Keys.COLLECT_PROGRESS_START, since=event.since, until=event.until)
    if event.stage == "collect_overview":
        breakdown = ", ".join(
            f"{agent_name} {count}" for agent_name, count in (event.agent_session_counts or {}).items()
        )
        overview = i18n.t(
            Keys.COLLECT_PROGRESS_OVERVIEW,
            session_count=event.session_count or event.current,
            chunk_count=event.chunk_count or 0,
            concurrency=event.concurrency or 1,
        )
        if not breakdown:
            return overview
        return "\n".join([overview, i18n.t(Keys.COLLECT_PROGRESS_AGENT_BREAKDOWN, breakdown=breakdown)])
    if event.stage == "scan_sessions":
        return i18n.t(Keys.COLLECT_PROGRESS_SCAN_SESSIONS, current=event.current, total=event.total)
    if event.stage == "plan_chunks":
        if event.current >= event.total:
            return i18n.t(
                Keys.COLLECT_PROGRESS_PLAN_CHUNKS_DONE,
                session_count=event.current,
                chunk_count=event.chunk_total or 0,
            )
        return i18n.t(Keys.COLLECT_PROGRESS_PLAN_CHUNKS, current=event.current, total=event.total)
    if event.stage == "summarize_chunks":
        return i18n.t(
            Keys.COLLECT_PROGRESS_SUMMARIZE_CHUNKS,
            current=event.current,
            total=event.total,
            concurrency=event.concurrency or 1,
        )
    if event.stage == "merge_sessions":
        return i18n.t(Keys.COLLECT_PROGRESS_MERGE_SESSIONS, current=event.current, total=event.total)
    if event.stage == "tree_reduction":
        level = event.level or 1
        return i18n.t(Keys.COLLECT_PROGRESS_TREE_REDUCTION, level=level, current=event.current, total=event.total)
    if event.stage == "render_final":
        return i18n.t(Keys.COLLECT_PROGRESS_RENDER_FINAL, current=event.current, total=event.total)
    if event.stage == "write_output":
        return i18n.t(Keys.COLLECT_PROGRESS_WRITE_OUTPUT, current=event.current, total=event.total)
    return event.message


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
        text = _format_collect_progress(event)
        if event.stage in {"collect_start", "collect_overview"}:
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
        f"{agent_name} {count}" for agent_name, count in sorted(run_stats.agent_session_counts.items())
    )
    return "\n".join(
        [
            i18n.t(Keys.COLLECT_DRY_RUN_HEADER),
            i18n.t(Keys.COLLECT_DRY_RUN_DATE_RANGE, since=run_stats.since, until=run_stats.until),
            i18n.t(Keys.COLLECT_DRY_RUN_PROVIDER_BREAKDOWN, breakdown=breakdown),
            i18n.t(Keys.COLLECT_DRY_RUN_SESSION_COUNT, count=run_stats.session_count),
            i18n.t(Keys.COLLECT_DRY_RUN_CHUNK_COUNT, count=run_stats.chunk_count),
            i18n.t(Keys.COLLECT_DRY_RUN_CONCURRENCY, concurrency=run_stats.concurrency),
            i18n.t(Keys.COLLECT_DRY_RUN_SAVE_PATH, path=str(output_path)),
        ]
    )


def handle_collect_mode(
    args: argparse.Namespace,
    *,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
    request_summary: Callable[..., str] = request_summary_from_llm,
) -> int:
    """Handle `--collect` flow."""
    dry_run = bool(getattr(args, "dry_run", False))

    if args.interactive or args.list:
        print(i18n.t(Keys.COLLECT_MODE_CONFLICT))
        return 1

    if args.uri and not args.uri.startswith("agents://"):
        print(i18n.t(Keys.COLLECT_MODE_CONFLICT))
        return 1

    try:
        since_date, until_date = resolve_collect_date_range(
            args.since,
            args.until,
            days=getattr(args, "days", None),
        )
    except ValueError as exc:
        if str(exc) == "since_after_until":
            print(i18n.t(Keys.COLLECT_DATE_RANGE_INVALID))
        else:
            print(i18n.t(Keys.COLLECT_DATE_FORMAT_INVALID))
        return 1

    config: AIConfig | None = None
    if not dry_run:
        config = load_ai_config()
        valid, errors = validate_ai_config(config)
        if not valid or config is None:
            if "missing_file" in errors:
                print(i18n.t(Keys.COLLECT_CONFIG_MISSING))
            else:
                print(i18n.t(Keys.COLLECT_CONFIG_INCOMPLETE, fields=",".join(errors)))
            print(i18n.t(Keys.COLLECT_CONFIG_HINT))
            return 1

    collect_config = load_collect_config()
    collect_logger = None
    if not dry_run:
        logging_config = load_logging_config()
        collect_logger = create_collect_logger(logging_config)

    scanner = scanner_factory()
    valid_agents = {agent.name for agent in scanner.agents}
    query_spec: QuerySpec | None = None
    if args.uri:
        try:
            query_spec = parse_query_uri(args.uri, valid_agents, Path.cwd())
        except ValueError as exc:
            print(i18n.t(Keys.QUERY_INVALID, error=exc))
            return 1
        if query_spec is None:
            print(i18n.t(Keys.COLLECT_MODE_CONFLICT))
            return 1

    available_agents: list[BaseAgent] = scanner.get_available_agents()
    if not available_agents:
        print(i18n.t(Keys.NO_AGENTS_FOUND))
        return 1

    collect_mode = getattr(args, "collect_mode", "pm")
    phase = "read"
    try:
        with show_collect_progress() as update_progress:
            emit_collect_progress(
                update_progress,
                stage="collect_start",
                current=0,
                total=1,
                message="collect start",
                since=since_date.isoformat(),
                until=until_date.isoformat(),
            )
            entries, has_truncated = collect_entries(
                agents=available_agents,
                since_date=since_date,
                until_date=until_date,
                collect_config=collect_config,
                query_spec=query_spec,
                render_session_text_fn=render_session_text,
                progress_callback=update_progress,
            )
            if not entries:
                print(i18n.t(Keys.COLLECT_NO_SESSIONS, since=since_date.isoformat(), until=until_date.isoformat()))
                return 1

            if collect_logger is not None:
                collect_logger.log(
                    "collect_run_start",
                    since=since_date.isoformat(),
                    until=until_date.isoformat(),
                    summary_concurrency=collect_config.summary_concurrency,
                    agent_count=len(available_agents),
                    session_count=len(entries),
                )
            planned_entries, _ = plan_collect_entries(entries, progress_callback=update_progress)
            run_stats = build_collect_run_stats(
                entries=entries,
                planned_entries=planned_entries,
                since_date=since_date,
                until_date=until_date,
                summary_concurrency=collect_config.summary_concurrency,
            )
            emit_collect_progress(
                update_progress,
                stage="collect_overview",
                current=run_stats.session_count,
                total=run_stats.session_count,
                message="collect overview",
                session_count=run_stats.session_count,
                chunk_count=run_stats.chunk_count,
                concurrency=run_stats.concurrency,
                since=run_stats.since,
                until=run_stats.until,
                agent_session_counts=run_stats.agent_session_counts,
            )
            if dry_run:
                print(
                    _format_collect_dry_run_preview(
                        run_stats=run_stats,
                        output_path=preview_collect_save_path(args.save, since_date=since_date, until_date=until_date),
                    )
                )
                return 0
            phase = "summarize"
            # dry-run 已在上方返回；非 dry-run 路径的 config 已通过校验
            ai_config = cast(AIConfig, config)
            session_summaries = summarize_collect_entries(
                config=ai_config,
                planned_entries=planned_entries,
                summary_concurrency=collect_config.summary_concurrency,
                progress_callback=update_progress,
                timeout_seconds=collect_config.summary_timeout_seconds,
                logger=collect_logger,
                mode=collect_mode,
            )
            phase = "render"
            emit_collect_progress(update_progress, stage="render_final", current=0, total=2, message="render final")
            aggregate = reduce_collect_summaries(
                config=ai_config,
                session_summaries=session_summaries,
                progress_callback=update_progress,
                timeout_seconds=collect_config.summary_timeout_seconds,
                logger=collect_logger,
                mode=collect_mode,
            )
            emit_collect_progress(update_progress, stage="render_final", current=1, total=2, message="render final")
            prompt = build_collect_final_prompt(
                since_date=since_date,
                until_date=until_date,
                aggregate=aggregate,
                has_truncated=has_truncated,
                mode=collect_mode,
            )
            markdown = request_summary(
                ai_config,
                prompt,
                timeout_seconds=collect_config.summary_timeout_seconds,
            )
            emit_collect_progress(update_progress, stage="render_final", current=2, total=2, message="render final")
            emit_collect_progress(update_progress, stage="write_output", current=0, total=1, message="write output")
            phase = "write"
            output_path = write_collect_markdown(
                markdown,
                since_date=since_date,
                until_date=until_date,
                output_path=resolve_collect_save_path(args.save, since_date=since_date, until_date=until_date),
            )
            emit_collect_progress(update_progress, stage="write_output", current=1, total=1, message="write output")
    except Exception as exc:
        if collect_logger is not None:
            collect_logger.log("collect_run_fail", phase=phase, error=str(exc))
        if phase == "read":
            print(i18n.t(Keys.COLLECT_READ_FAILED, error=exc))
        else:
            print(i18n.t(Keys.COLLECT_API_FAILED, error=exc))
        return 1

    if collect_logger is not None:
        collect_logger.log("collect_run_finish", output_path=str(output_path), session_count=len(entries))
    print(markdown)
    print(i18n.t(Keys.COLLECT_OUTPUT_SAVED, path=str(output_path)))
    return 0
