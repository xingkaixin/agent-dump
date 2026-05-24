import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import VALID_URI_SCHEMES
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


@dataclass(frozen=True)
class UriModeDeps:
    scanner_factory: Callable[[], AgentScanner]
    parse_uri: Callable[[str], tuple[str, str] | None]
    find_session_by_id: Callable[..., tuple[BaseAgent, Session] | None]
    render_session_head: Callable[[str, dict[str, Any]], str]
    maybe_generate_uri_summary: Callable[..., tuple[dict[str, Any] | None, str | None]]
    render_session_text: Callable[[str, dict[str, Any]], str]
    export_session_in_format: Callable[..., Path]
    apply_summary_to_json_export: Callable[[Path, str], None]
    resolve_output_base_dir: Callable[..., Path]
    validate_uri_agent_formats: Callable[[BaseAgent, list[str]], None]
    print_diagnostic: Callable[[DiagnosticError], None]
    build_no_agents_found_diagnostic: Callable[[AgentScanner], DiagnosticError]
    wrap_runtime_fetch_error: Callable[..., DiagnosticError]
    render_agent_search_roots: Callable[[list[Any]], tuple[str, ...]]
    get_supported_uri_examples: Callable[[], list[str]]


def handle_uri_mode(
    args: argparse.Namespace,
    *,
    output_formats: list[str],
    output_specified: bool,
    export_config: ExportConfigLike,
    deps: UriModeDeps,
) -> int:
    uri_result = deps.parse_uri(args.uri)
    if uri_result is None:
        deps.print_diagnostic(
            invalid_query_or_uri(
                "URI 格式无效。",
                details=("无法解析为受支持的 `<scheme>://<session_id>` 形式。",),
                parsed_uri=ParsedUri(raw=args.uri),
                next_steps=(
                    "改用受支持的 URI scheme。",
                    *[example.strip() for example in deps.get_supported_uri_examples()],
                ),
            )
        )
        return 1

    scheme, session_id = uri_result

    scanner = deps.scanner_factory()
    available_agents = scanner.get_available_agents()

    if not available_agents:
        deps.print_diagnostic(deps.build_no_agents_found_diagnostic(scanner))
        return 1

    expected_agent_name = VALID_URI_SCHEMES.get(scheme)
    result = deps.find_session_by_id(scanner, session_id, agent_name=expected_agent_name)
    if result is None:
        deps.print_diagnostic(
            session_not_found(
                raw_uri=args.uri,
                scheme=scheme,
                session_id=session_id,
                searched_roots=deps.render_agent_search_roots(scanner.agents),
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
        deps.print_diagnostic(
            invalid_query_or_uri(
                "URI scheme 与实际会话来源不匹配。",
                details=(f"该会话实际属于 {agent.display_name}。",),
                parsed_uri=ParsedUri(raw=args.uri, scheme=scheme, session_id=session_id),
                next_steps=(f"改用 `{agent.get_session_uri(session)}` 重新执行。",),
            )
        )
        return 1
    try:
        deps.validate_uri_agent_formats(agent, output_formats)
    except DiagnosticError as e:
        deps.print_diagnostic(e)
        return 1

    try:
        had_success = False
        if args.head:
            print(deps.render_session_head(args.uri, agent.get_session_head(session)))
            return 0

        session_data: dict[str, Any] | None = None
        session_data, summary_markdown = deps.maybe_generate_uri_summary(
            enabled=args.summary,
            output_formats=output_formats,
            uri=args.uri,
            agent=agent,
            session=session,
            session_data=session_data,
        )
        if "print" in output_formats:
            session_data = session_data if session_data is not None else agent.get_session_data(session)
            output = deps.render_session_text(args.uri, session_data)
            print(output)
            had_success = True

        file_formats = [fmt for fmt in output_formats if fmt != "print"]
        for output_format in file_formats:
            try:
                output_dir = (
                    deps.resolve_output_base_dir(
                        cli_output=args.output,
                        output_specified=output_specified,
                        export_output=export_config.output,
                        output_format=output_format,
                    )
                    / agent.name
                )
                output_path = deps.export_session_in_format(
                    agent,
                    session,
                    output_dir,
                    output_format,
                    session_data=session_data,
                    session_uri=args.uri,
                )
                if output_format == "json" and summary_markdown is not None:
                    try:
                        deps.apply_summary_to_json_export(output_path, summary_markdown)
                        print(i18n.t(Keys.URI_SUMMARY_APPLIED, path=str(output_path)))
                    except Exception as e:
                        print(i18n.t(Keys.URI_SUMMARY_API_FAILED_WARNING, error=e))
                print(i18n.t(Keys.URI_EXPORT_SAVED, path=str(output_path), format=output_format))
                had_success = True
            except Exception as e:
                diagnostic = e if isinstance(e, DiagnosticError) else deps.wrap_runtime_fetch_error(e, agent=agent)
                deps.print_diagnostic(diagnostic)
        return 0 if had_success else 1
    except Exception as e:
        diagnostic = e if isinstance(e, DiagnosticError) else deps.wrap_runtime_fetch_error(e, agent=agent)
        deps.print_diagnostic(diagnostic)
        return 1
