"""Collect mode workflow orchestration."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from agent_dump.agents.base import BaseAgent


@dataclass(frozen=True)
class CollectWorkflowDeps:
    """Injected dependencies for collect mode orchestration."""

    resolve_collect_date_range: Callable[..., tuple[date, date]]
    load_ai_config: Callable[[], Any]
    validate_ai_config: Callable[[Any], tuple[bool, list[str]]]
    load_collect_config: Callable[[], Any]
    load_logging_config: Callable[[], Any]
    create_collect_logger: Callable[[Any], Any]
    scanner_factory: Callable[[], Any]
    show_collect_progress: Callable[[], Any]
    collect_entries: Callable[..., tuple[list[Any], bool]]
    plan_collect_entries: Callable[..., list[Any]]
    summarize_collect_entries: Callable[..., list[Any]]
    emit_collect_progress: Callable[..., None]
    reduce_collect_summaries: Callable[..., Any]
    build_collect_final_prompt: Callable[..., str]
    request_summary_from_llm: Callable[..., str]
    write_collect_markdown: Callable[..., Path]
    resolve_collect_save_path: Callable[..., Path | None]
    render_session_text: Callable[[str, dict[str, Any]], str]
    i18n_t: Callable[..., str]
    keys: Any


def resolve_collect_save_path(save: str | None, *, since_date: date, until_date: date) -> Path | None:
    """Resolve collect output path from an optional save spec."""
    if save is None:
        return None

    candidate = Path(save)
    default_name = f"agent-dump-collect-{since_date.strftime('%Y%m%d')}-{until_date.strftime('%Y%m%d')}.md"

    if candidate.exists():
        return candidate / default_name if candidate.is_dir() else candidate
    if candidate.suffix.lower() == ".md":
        return candidate
    return candidate / default_name


def handle_collect_mode(args: argparse.Namespace, deps: CollectWorkflowDeps) -> int:
    """Handle `--collect` flow."""
    keys = deps.keys
    t = deps.i18n_t

    if args.uri or args.interactive or args.list:
        print(t(keys.COLLECT_MODE_CONFLICT))
        return 1

    try:
        since_date, until_date = deps.resolve_collect_date_range(args.since, args.until)
    except ValueError as exc:
        if str(exc) == "since_after_until":
            print(t(keys.COLLECT_DATE_RANGE_INVALID))
        else:
            print(t(keys.COLLECT_DATE_FORMAT_INVALID))
        return 1

    config = deps.load_ai_config()
    valid, errors = deps.validate_ai_config(config)
    if not valid or config is None:
        if "missing_file" in errors:
            print(t(keys.COLLECT_CONFIG_MISSING))
        else:
            print(t(keys.COLLECT_CONFIG_INCOMPLETE, fields=",".join(errors)))
        print(t(keys.COLLECT_CONFIG_HINT))
        return 1

    collect_config = deps.load_collect_config()
    logging_config = deps.load_logging_config()
    collect_logger = deps.create_collect_logger(logging_config)

    scanner = deps.scanner_factory()
    available_agents: list[BaseAgent] = scanner.get_available_agents()
    if not available_agents:
        print(t(keys.NO_AGENTS_FOUND))
        return 1

    phase = "read"
    try:
        with deps.show_collect_progress() as update_progress:
            entries, has_truncated = deps.collect_entries(
                agents=available_agents,
                since_date=since_date,
                until_date=until_date,
                collect_config=collect_config,
                render_session_text_fn=deps.render_session_text,
                progress_callback=update_progress,
            )
            if not entries:
                print(t(keys.COLLECT_NO_SESSIONS, since=since_date.isoformat(), until=until_date.isoformat()))
                return 1

            collect_logger.log(
                "collect_run_start",
                since=since_date.isoformat(),
                until=until_date.isoformat(),
                summary_concurrency=collect_config.summary_concurrency,
                agent_count=len(available_agents),
                session_count=len(entries),
            )
            planned_entries = deps.plan_collect_entries(entries, progress_callback=update_progress)
            phase = "summarize"
            session_summaries = deps.summarize_collect_entries(
                config=config,
                planned_entries=planned_entries,
                summary_concurrency=collect_config.summary_concurrency,
                progress_callback=update_progress,
                timeout_seconds=collect_config.summary_timeout_seconds,
                logger=collect_logger,
            )
            phase = "render"
            deps.emit_collect_progress(
                update_progress, stage="render_final", current=0, total=2, message="render final"
            )
            aggregate = deps.reduce_collect_summaries(
                config=config,
                session_summaries=session_summaries,
                progress_callback=update_progress,
                timeout_seconds=collect_config.summary_timeout_seconds,
                logger=collect_logger,
            )
            deps.emit_collect_progress(
                update_progress, stage="render_final", current=1, total=2, message="render final"
            )
            prompt = deps.build_collect_final_prompt(
                since_date=since_date,
                until_date=until_date,
                aggregate=aggregate,
                has_truncated=has_truncated,
            )
            markdown = deps.request_summary_from_llm(
                config,
                prompt,
                timeout_seconds=collect_config.summary_timeout_seconds,
            )
            deps.emit_collect_progress(
                update_progress, stage="render_final", current=2, total=2, message="render final"
            )
            deps.emit_collect_progress(
                update_progress, stage="write_output", current=0, total=1, message="write output"
            )
            phase = "write"
            output_path = deps.write_collect_markdown(
                markdown,
                since_date=since_date,
                until_date=until_date,
                output_path=deps.resolve_collect_save_path(args.save, since_date=since_date, until_date=until_date),
            )
            deps.emit_collect_progress(
                update_progress, stage="write_output", current=1, total=1, message="write output"
            )
    except Exception as exc:
        collect_logger.log("collect_run_fail", phase=phase, error=str(exc))
        if phase == "read":
            print(t(keys.COLLECT_READ_FAILED, error=exc))
        else:
            print(t(keys.COLLECT_API_FAILED, error=exc))
        return 1

    collect_logger.log("collect_run_finish", output_path=str(output_path), session_count=len(entries))
    print(markdown)
    print(t(keys.COLLECT_OUTPUT_SAVED, path=str(output_path)))
    return 0
