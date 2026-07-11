import argparse
from collections.abc import Callable
from typing import Any, Protocol

from agent_dump.agent_registry import get_supported_uri_examples
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import (
    VALID_URI_SCHEMES,
    apply_summary_to_json_export,
    build_no_agents_found_diagnostic,
    export_session_in_format,
    find_session_by_id,
    parse_uri,
    print_diagnostic,
    render_agent_search_roots,
    render_session_head,
    render_session_text,
    resolve_output_base_dir,
    show_loading,
    validate_uri_agent_formats,
    wrap_runtime_fetch_error,
)
from agent_dump.collect import request_summary_from_llm
from agent_dump.config import AIConfig, load_ai_config, validate_ai_config
from agent_dump.diagnostics import (
    DiagnosticError,
    ParsedUri,
    invalid_query_or_uri,
    session_not_found,
)
from agent_dump.i18n import Keys, i18n
from agent_dump.scanner import AgentScanner


class ExportConfigLike(Protocol):
    output: str


def build_uri_summary_prompt(uri: str, rendered_session_text: str) -> str:
    """Build a single-session summary prompt for URI mode."""
    return "\n".join(
        [
            "你是一个严谨的会话总结助手。",
            "请基于下面的单个会话内容输出 Markdown 总结。",
            "要求：",
            "1. 只基于给定内容，不要编造。",
            "2. 总结关键目标、主要改动、风险/异常、结果。",
            "3. 若信息不足，明确指出。",
            "",
            f"会话 URI: {uri}",
            "",
            "会话内容：",
            rendered_session_text,
        ]
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
        if "missing_file" in errors:
            print(i18n.t(Keys.URI_SUMMARY_CONFIG_MISSING_WARNING))
        else:
            print(i18n.t(Keys.URI_SUMMARY_CONFIG_INCOMPLETE_WARNING, fields=",".join(errors)))
        return session_data, None

    effective_session_data = session_data if session_data is not None else agent.get_session_data(session)
    rendered = render_session_text(uri, effective_session_data)
    prompt = build_uri_summary_prompt(uri, rendered)

    try:
        with show_loading(i18n.t(Keys.URI_SUMMARY_LOADING)):
            summary_markdown = request_summary(config, prompt)
    except Exception as e:
        print(i18n.t(Keys.URI_SUMMARY_API_FAILED_WARNING, error=e))
        return effective_session_data, None

    return effective_session_data, summary_markdown


def handle_uri_mode(
    args: argparse.Namespace,
    *,
    output_formats: list[str],
    output_specified: bool,
    export_config: ExportConfigLike,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
    request_summary: Callable[[AIConfig, str], str] = request_summary_from_llm,
) -> int:
    uri_result = parse_uri(args.uri)
    if uri_result is None:
        print_diagnostic(
            invalid_query_or_uri(
                "URI 格式无效。",
                details=("无法解析为受支持的 `<scheme>://<session_id>` 形式。",),
                parsed_uri=ParsedUri(raw=args.uri),
                next_steps=(
                    "改用受支持的 URI scheme。",
                    *[example.strip() for example in get_supported_uri_examples()],
                ),
            )
        )
        return 1

    scheme, session_id = uri_result

    scanner = scanner_factory()
    available_agents = scanner.get_available_agents()

    if not available_agents:
        print_diagnostic(build_no_agents_found_diagnostic(scanner))
        return 1

    expected_agent_name = VALID_URI_SCHEMES.get(scheme)
    result = find_session_by_id(scanner, session_id, agent_name=expected_agent_name)
    if result is None:
        print_diagnostic(
            session_not_found(
                raw_uri=args.uri,
                scheme=scheme,
                session_id=session_id,
                searched_roots=render_agent_search_roots(scanner.agents),
                details=("已扫描当前可用 provider，但未匹配到该 session id。",),
                next_steps=(
                    "先运行 `agent-dump --list` 确认该会话是否仍存在。",
                    "检查 URI 中的 session id 是否完整且对应正确 provider。",
                ),
            )
        )
        return 1

    agent, session = result

    if agent.name != expected_agent_name:
        print_diagnostic(
            invalid_query_or_uri(
                "URI scheme 与实际会话来源不匹配。",
                details=(f"该会话实际属于 {agent.display_name}。",),
                parsed_uri=ParsedUri(raw=args.uri, scheme=scheme, session_id=session_id),
                next_steps=(f"改用 `{agent.get_session_uri(session)}` 重新执行。",),
            )
        )
        return 1
    try:
        validate_uri_agent_formats(agent, output_formats)
    except DiagnosticError as e:
        print_diagnostic(e)
        return 1

    try:
        had_success = False
        if args.head:
            print(render_session_head(args.uri, agent.get_session_head(session)))
            return 0

        session_data: dict[str, Any] | None = None
        session_data, summary_markdown = maybe_generate_uri_summary(
            enabled=args.summary,
            output_formats=output_formats,
            uri=args.uri,
            agent=agent,
            session=session,
            session_data=session_data,
            request_summary=request_summary,
        )
        if "print" in output_formats:
            session_data = session_data if session_data is not None else agent.get_session_data(session)
            output = render_session_text(args.uri, session_data)
            print(output)
            had_success = True

        file_formats = [fmt for fmt in output_formats if fmt != "print"]
        for output_format in file_formats:
            try:
                output_dir = (
                    resolve_output_base_dir(
                        cli_output=args.output,
                        output_specified=output_specified,
                        export_output=export_config.output,
                        output_format=output_format,
                    )
                    / agent.name
                )
                output_path = export_session_in_format(
                    agent,
                    session,
                    output_dir,
                    output_format,
                    session_data=session_data,
                    session_uri=args.uri,
                )
                if output_format == "json" and summary_markdown is not None:
                    try:
                        apply_summary_to_json_export(output_path, summary_markdown)
                        print(i18n.t(Keys.URI_SUMMARY_APPLIED, path=str(output_path)))
                    except Exception as e:
                        print(i18n.t(Keys.URI_SUMMARY_API_FAILED_WARNING, error=e))
                print(i18n.t(Keys.URI_EXPORT_SAVED, path=str(output_path), format=output_format))
                had_success = True
            except Exception as e:
                diagnostic = e if isinstance(e, DiagnosticError) else wrap_runtime_fetch_error(e, agent=agent)
                print_diagnostic(diagnostic)
        return 0 if had_success else 1
    except Exception as e:
        diagnostic = e if isinstance(e, DiagnosticError) else wrap_runtime_fetch_error(e, agent=agent)
        print_diagnostic(diagnostic)
        return 1
