from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import (
    print_diagnostic,
    render_agent_search_roots,
    resolve_output_base_dir,
    show_loading,
    wrap_runtime_fetch_error,
)
from agent_dump.collect import request_summary_from_llm
from agent_dump.command_plan import UriOperation
from agent_dump.config import AIConfig, AIConfigError, load_ai_config, validate_ai_config
from agent_dump.diagnostics import DiagnosticError, session_not_found
from agent_dump.exporting import execute_exports
from agent_dump.i18n import Keys, i18n
from agent_dump.output_formats import validate_uri_agent_formats
from agent_dump.prompt_safety import UntrustedData, compose_summary_prompt
from agent_dump.rendering import render_session_head, render_session_text
from agent_dump.scanner import AgentScanner
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import safe_body_text
from agent_dump.uri_support import find_session_by_id


class ExportConfigLike(Protocol):
    @property
    def output(self) -> str: ...


def build_uri_summary_prompt(uri: str, rendered_session_text: str) -> str:
    """Build a single-session summary prompt for URI mode."""
    return compose_summary_prompt(
        (
            "任务：严谨总结给定的单个会话。",
            "请基于下面的单个会话内容输出 Markdown 总结。",
            "要求：",
            "1. 只基于给定内容，不要编造。",
            "2. 总结关键目标、主要改动、风险/异常、结果。",
            "3. 若信息不足，明确指出。",
        ),
        data=(UntrustedData(kind="session_transcript", source=uri, body=rendered_session_text),),
    )


def maybe_generate_uri_summary(
    *,
    enabled: bool,
    output_formats: list[str],
    uri: str,
    agent: BaseAgent,
    session: Session,
    session_data: dict[str, Any] | None,
    request_summary: Callable[[AIConfig, str], str] = request_summary_from_llm,
) -> tuple[dict[str, Any] | None, str | None]:
    """Best-effort URI summary generation. Returns possibly-loaded session_data and summary."""
    if not enabled:
        return session_data, None

    if "json" not in output_formats:
        print(i18n.t(Keys.URI_SUMMARY_NO_JSON_WARNING))
        return session_data, None

    config = load_ai_config()
    valid, errors = validate_ai_config(config)
    if not valid or config is None:
        if AIConfigError.MISSING_FILE in errors:
            print(i18n.t(Keys.URI_SUMMARY_CONFIG_MISSING_WARNING))
        elif AIConfigError.BASE_URL_SCHEME in errors:
            print(i18n.t(Keys.COLLECT_CONFIG_BAD_SCHEME))
        elif AIConfigError.BASE_URL_PLAINTEXT_KEY in errors:
            print(i18n.t(Keys.COLLECT_CONFIG_PLAINTEXT_KEY))
        else:
            print(
                render_terminal_message(
                    Keys.URI_SUMMARY_CONFIG_INCOMPLETE_WARNING,
                    fields=",".join(error.value for error in errors),
                )
            )
        return session_data, None

    effective_session_data = session_data if session_data is not None else agent.get_cached_session_data(session)
    rendered = render_session_text(uri, effective_session_data)
    prompt = build_uri_summary_prompt(uri, rendered)

    try:
        with show_loading(i18n.t(Keys.URI_SUMMARY_LOADING)):
            summary_markdown = request_summary(config, prompt)
    except Exception as e:
        print(render_terminal_message(Keys.URI_SUMMARY_API_FAILED_WARNING, error=e))
        return effective_session_data, None

    return effective_session_data, summary_markdown


def handle_uri_mode(
    operation: UriOperation,
    *,
    export_config: ExportConfigLike,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
    request_summary: Callable[[AIConfig, str], str] = request_summary_from_llm,
) -> int:
    scanner = scanner_factory()
    with scanner.diagnostic_scope():
        return _handle_uri_mode(
            operation,
            export_config=export_config,
            scanner=scanner,
            request_summary=request_summary,
        )


def _handle_uri_mode(
    operation: UriOperation,
    *,
    export_config: ExportConfigLike,
    scanner: AgentScanner,
    request_summary: Callable[[AIConfig, str], str],
) -> int:
    result = find_session_by_id(
        scanner,
        operation.session_id,
        agent_name=operation.expected_agent_name,
    )
    if result is None:
        print_diagnostic(
            session_not_found(
                raw_uri=operation.raw_uri,
                scheme=operation.scheme,
                session_id=operation.session_id,
                searched_roots=render_agent_search_roots(scanner.agents),
                details=(i18n.t(Keys.DIAG_URI_SCANNED_NO_MATCH),),
                next_steps=(
                    i18n.t(Keys.DIAG_STEP_LIST_TO_CONFIRM),
                    i18n.t(Keys.DIAG_STEP_CHECK_URI_SESSION_ID),
                ),
            )
        )
        return 1

    agent, session = result
    try:
        validate_uri_agent_formats(agent, list(operation.output_formats))
    except DiagnosticError as e:
        print_diagnostic(e)
        return 1

    try:
        had_success = False
        if operation.head:
            print(render_session_head(operation.raw_uri, agent.get_session_head(session)))
            return 0

        session_data: dict[str, Any] | None = None
        session_data, summary_markdown = maybe_generate_uri_summary(
            enabled=operation.summary,
            output_formats=list(operation.output_formats),
            uri=operation.raw_uri,
            agent=agent,
            session=session,
            session_data=session_data,
            request_summary=request_summary,
        )
        if "print" in operation.output_formats:
            session_data = session_data if session_data is not None else agent.get_cached_session_data(session)
            output = render_session_text(operation.raw_uri, session_data)
            print(safe_body_text(output))
            had_success = True

        file_formats = [fmt for fmt in operation.output_formats if fmt != "print"]

        def _output_dir_for_format(output_format: str) -> Path:
            return (
                resolve_output_base_dir(
                    cli_output=operation.output,
                    output_specified=operation.output_specified,
                    export_output=export_config.output,
                    output_format=output_format,
                )
                / agent.name
            )

        export_result = execute_exports(
            agent,
            [session],
            file_formats,
            _output_dir_for_format,
            prepared_session_data={session.id: session_data} if session_data is not None else None,
            session_uris={session.id: operation.raw_uri},
            summaries={session.id: summary_markdown} if summary_markdown is not None else None,
        )
        for attempt in export_result.attempts:
            if attempt.output_path is None:
                error = attempt.error or RuntimeError("export failed without an error")
                diagnostic = (
                    error if isinstance(error, DiagnosticError) else wrap_runtime_fetch_error(error, agent=agent)
                )
                print_diagnostic(diagnostic)
                continue

            if attempt.output_format == "json" and summary_markdown is not None:
                if attempt.error is None:
                    print(render_terminal_message(Keys.URI_SUMMARY_APPLIED, path=attempt.output_path))
                else:
                    print(render_terminal_message(Keys.URI_SUMMARY_API_FAILED_WARNING, error=attempt.error))
            print(
                render_terminal_message(
                    Keys.URI_EXPORT_SAVED,
                    path=attempt.output_path,
                    format=attempt.output_format,
                )
            )
        had_success = had_success or export_result.had_success
        return 0 if had_success else 1
    except Exception as e:
        diagnostic = e if isinstance(e, DiagnosticError) else wrap_runtime_fetch_error(e, agent=agent)
        print_diagnostic(diagnostic)
        return 1
