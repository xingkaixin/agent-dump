from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import (
    build_no_agents_found_diagnostic,
    collect_query_matches,
    print_diagnostic,
    resolve_output_base_dir,
    scope_session_groups_by_provider,
    wrap_runtime_fetch_error,
)
from agent_dump.command_plan import InteractiveOperation, ListOperation, SearchOperation, SessionOperation
from agent_dump.config import ExportConfig
from agent_dump.diagnostics import DiagnosticError, print_recoverable_diagnostic, render_diagnostic
from agent_dump.exporting import ExportFailure, ExportRunResult, execute_exports
from agent_dump.i18n import Keys, i18n
from agent_dump.output_formats import FileOutputFormat, validate_agent_formats
from agent_dump.query_filter import QuerySessionMatch, QuerySpec, select_session_groups
from agent_dump.rendering import format_session_metadata_summary
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import safe_display_text
from agent_dump.time_utils import to_local_datetime


def display_sessions_list(
    agent: BaseAgent,
    sessions: list[Session],
    show_metadata_summary: bool = True,
) -> None:
    if not sessions:
        print(i18n.t(Keys.NO_SESSIONS_PAREN))
        return

    for session in sessions:
        title = safe_display_text(agent.get_formatted_title(session))
        if show_metadata_summary:
            summary = safe_display_text(format_session_metadata_summary(agent, session))
            print(f"   • {title}")
            print(f"     {summary}")
        else:
            uri = safe_display_text(agent.get_session_uri(session))
            print(f"   • {title} {uri}")


def export_sessions_for_formats(
    agent: BaseAgent,
    sessions: list[Session],
    formats: list[FileOutputFormat],
    output_base_dirs: Mapping[FileOutputFormat, Path],
) -> ExportRunResult:
    print(render_terminal_message(Keys.EXPORTING_AGENT, agent_name=agent.display_name))

    def _output_dir_for_format(output_format: FileOutputFormat) -> Path:
        return output_base_dirs[output_format] / agent.name

    result = execute_exports(
        agent,
        sessions,
        formats,
        _output_dir_for_format,
        session_uris={session.id: agent.get_session_uri(session) for session in sessions},
    )
    for attempt in result.attempts:
        if not isinstance(attempt, ExportFailure):
            print(
                render_terminal_message(
                    Keys.EXPORT_SUCCESS_FORMAT,
                    title=attempt.session.title[:50],
                    format=attempt.output_format,
                    filename=attempt.output_path.name,
                )
            )
            continue

        error = attempt.error
        diagnostic = error if isinstance(error, DiagnosticError) else wrap_runtime_fetch_error(error, agent=agent)
        print(render_diagnostic(diagnostic, t=i18n.t))

    return result


def render_query_summary(spec: QuerySpec) -> str:
    if (
        spec.project_path is None
        and spec.agent_names is None
        and spec.roles is None
        and spec.limit is None
        and spec.keyword
    ):
        return safe_display_text(spec.keyword)

    parts: list[str] = []
    if spec.project_path is not None:
        parts.append(render_terminal_message(Keys.QUERY_SUMMARY_PATH, path=spec.project_path))
    if spec.keyword:
        parts.append(render_terminal_message(Keys.QUERY_SUMMARY_KEYWORD, keyword=spec.keyword))
    if spec.agent_names:
        providers = safe_display_text(",".join(sorted(spec.agent_names)))
        parts.append(f"providers={providers}")
    if spec.roles:
        roles = safe_display_text(",".join(sorted(spec.roles)))
        parts.append(f"roles={roles}")
    if spec.limit is not None:
        parts.append(f"limit={spec.limit}")
    return i18n.t(Keys.QUERY_SUMMARY_SEPARATOR).join(parts) if parts else i18n.t(Keys.QUERY_SUMMARY_ALL_SESSIONS)


def collect_search_matches(
    session_groups: Sequence[tuple[BaseAgent, list[Session]]],
    *,
    spec: QuerySpec,
) -> list[QuerySessionMatch]:
    return select_session_groups(session_groups, spec, diagnostic_sink=print_recoverable_diagnostic)


def display_search_results(matches: list[QuerySessionMatch]) -> None:
    if not matches:
        print(i18n.t(Keys.SEARCH_NO_RESULTS))
        return

    for index, match in enumerate(matches, start=1):
        title = match.agent.get_formatted_title(match.session)
        uri = match.agent.get_session_uri(match.session)
        updated = to_local_datetime(match.session.updated_at).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"\n{index}. {safe_display_text(title)}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_PROVIDER)}: {safe_display_text(match.agent.display_name)}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_UPDATED)}: {updated}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_URI)}: {safe_display_text(uri)}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_RANK)}: {match.rank:.6g}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_SNIPPET)}: {safe_display_text(match.snippet)}")


def warn_list_ignored_options(output_specified: bool, format_specified: bool) -> None:
    if format_specified:
        print(i18n.t(Keys.LIST_IGNORE_FORMAT))
    if output_specified:
        print(i18n.t(Keys.LIST_IGNORE_OUTPUT))


def handle_session_modes(
    operation: SessionOperation,
    *,
    export_config: ExportConfig,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
) -> int | None:
    scanner = scanner_factory()
    with scanner.diagnostic_context():
        return _handle_session_modes(operation, export_config=export_config, scanner=scanner)


def _handle_session_modes(
    operation: SessionOperation,
    *,
    export_config: ExportConfig,
    scanner: AgentScanner,
) -> int | None:
    print("🚀 Agent Session Exporter\n")
    print("=" * 60 + "\n")

    query_spec = operation.query_spec

    scanned_sessions = scanner.get_available_sessions(operation.days)
    if not scanned_sessions:
        # 退 1 而不是 None：这里走的是诊断通道（错误语义），而 --stats / --reindex /
        # URI 模式在同一条件下已经退 1。约定见 README 的 Exit Codes 一节。
        print_diagnostic(build_no_agents_found_diagnostic(scanner))
        return 1

    scanned_sessions, scope_error = scope_session_groups_by_provider(
        scanned_sessions,
        agent_names=query_spec.agent_names if query_spec is not None else None,
        all_agents=scanner.agents,
    )
    if scope_error is not None:
        print_diagnostic(scope_error)
        return 1 if isinstance(operation, InteractiveOperation) else 0
    available_agents = [agent for agent, _ in scanned_sessions]

    if isinstance(operation, SearchOperation):
        search_spec = operation.query_spec
        warn_list_ignored_options(operation.output_specified, operation.format_specified)
        print(
            render_terminal_message(
                Keys.SEARCH_HEADER,
                days=operation.days,
                query=render_query_summary(search_spec),
            )
        )
        print("-" * 60)
        display_search_results(
            collect_search_matches(
                scanned_sessions,
                spec=search_spec,
            )
        )
        print("\n" + "=" * 60)
        return 0

    matched_sessions_by_agent: dict[str, list[Session]] = {}
    if query_spec:
        matched_sessions_by_agent = collect_query_matches(
            scanned_sessions,
            spec=query_spec,
        )

    if isinstance(operation, ListOperation):
        return _handle_list_mode(
            operation,
            query_spec=query_spec,
            matched_sessions_by_agent=matched_sessions_by_agent,
            available_agents=available_agents,
            scanned_sessions=scanned_sessions,
        )

    return _handle_interactive_mode(
        operation,
        query_spec=query_spec,
        matched_sessions_by_agent=matched_sessions_by_agent,
        available_agents=available_agents,
        scanned_sessions=scanned_sessions,
        export_config=export_config,
    )


def _handle_list_mode(
    operation: ListOperation,
    *,
    query_spec: QuerySpec | None,
    matched_sessions_by_agent: dict[str, list[Session]],
    available_agents: list[BaseAgent],
    scanned_sessions: list[tuple[BaseAgent, list[Session]]],
) -> int:
    warn_list_ignored_options(operation.output_specified, operation.format_specified)
    if query_spec:
        print(
            render_terminal_message(
                Keys.LIST_HEADER_FILTERED,
                days=operation.days,
                query=render_query_summary(query_spec),
            )
        )
    else:
        print(i18n.t(Keys.LIST_HEADER, days=operation.days))
    print("-" * 60)

    listed = (
        [(agent, matched_sessions_by_agent.get(agent.name, [])) for agent in available_agents]
        if query_spec
        else scanned_sessions
    )
    for agent, sessions in listed:
        print(f"\n📁 {safe_display_text(agent.display_name)} ({len(sessions)} {i18n.t(Keys.SESSION_COUNT_SUFFIX)})")

        if sessions:
            display_sessions_list(
                agent,
                sessions,
                show_metadata_summary=operation.show_metadata_summary,
            )
        else:
            print(i18n.t(Keys.NO_SESSIONS_IN_DAYS, days=operation.days))

    print("\n" + "=" * 60)
    print(i18n.t(Keys.HINT_INTERACTIVE))
    print()
    return 0


def _handle_interactive_mode(
    operation: InteractiveOperation,
    *,
    query_spec: QuerySpec | None,
    matched_sessions_by_agent: dict[str, list[Session]],
    available_agents: list[BaseAgent],
    scanned_sessions: list[tuple[BaseAgent, list[Session]]],
    export_config: ExportConfig,
) -> int:
    # 一次取全，选中后直接复用；之前无 query 时 selector 会为标签逐个扫 provider，
    # 用户选完再把选中的 provider 完整扫第二遍
    if query_spec:
        sessions_by_agent = {
            agent.name: matched_sessions_by_agent[agent.name]
            for agent in available_agents
            if agent.name in matched_sessions_by_agent
        }
    else:
        sessions_by_agent = {agent.name: sessions for agent, sessions in scanned_sessions}

    session_counts = {name: len(sessions) for name, sessions in sessions_by_agent.items()}
    interactive_agents = [agent for agent in available_agents if agent.name in sessions_by_agent]

    if query_spec and not interactive_agents:
        print(
            render_terminal_message(
                Keys.NO_SESSIONS_MATCHING_KEYWORD,
                days=operation.days,
                query=render_query_summary(query_spec),
            )
        )
        return 1

    if len(interactive_agents) == 1:
        selected_agent = interactive_agents[0]
        print(render_terminal_message(Keys.AUTO_SELECT_AGENT, agent_name=selected_agent.display_name))
    else:
        selected_agent = select_agent_interactive(interactive_agents, session_counts)
        if not selected_agent:
            print("\n" + i18n.t(Keys.NO_AGENT_SELECTED))
            return 1
        print(render_terminal_message(Keys.AGENT_SELECTED, agent_name=selected_agent.display_name))

    try:
        validate_agent_formats(selected_agent, operation.output_formats)
    except DiagnosticError as error:
        print_diagnostic(error)
        return 1

    sessions = sessions_by_agent.get(selected_agent.name, [])

    if not sessions:
        if query_spec:
            print(
                render_terminal_message(
                    Keys.NO_SESSIONS_MATCHING_KEYWORD,
                    days=operation.days,
                    query=render_query_summary(query_spec),
                )
            )
        else:
            print(i18n.t(Keys.NO_SESSIONS_FOUND, days=operation.days))
        return 1

    if query_spec:
        print(
            render_terminal_message(
                Keys.SESSIONS_FOUND_FILTERED,
                count=len(sessions),
                days=operation.days,
                query=render_query_summary(query_spec),
            )
        )
    else:
        print(i18n.t(Keys.SESSIONS_FOUND, count=len(sessions), days=operation.days))

    if len(sessions) > 100:
        print(i18n.t(Keys.MANY_SESSIONS_WARNING, count=len(sessions)))
        print(i18n.t(Keys.MANY_SESSIONS_EXAMPLE))

    selected_sessions = select_sessions_interactive(
        sessions,
        selected_agent,
        show_metadata_summary=operation.show_metadata_summary,
    )
    if not selected_sessions:
        print("\n" + i18n.t(Keys.NO_SESSION_SELECTED))
        return 1

    print(i18n.t(Keys.SESSIONS_SELECTED_COUNT, count=len(selected_sessions)))

    output_base_dirs: dict[FileOutputFormat, Path] = {
        output_format: resolve_output_base_dir(
            cli_output=operation.output,
            output_specified=operation.output_specified,
            export_output=export_config.output,
            output_format=output_format,
        )
        for output_format in operation.output_formats
    }
    primary_output_format = operation.output_formats[0]
    primary_output_base_dir = output_base_dirs[primary_output_format]
    export_result = export_sessions_for_formats(
        selected_agent,
        selected_sessions,
        list(operation.output_formats),
        output_base_dirs,
    )

    summary_paths = sorted({str(path.parent) for path in export_result.exported_paths})
    summary_path = ", ".join(summary_paths) if summary_paths else f"{primary_output_base_dir}/{selected_agent.name}"
    print(render_terminal_message(Keys.EXPORT_SUMMARY, count=len(export_result), path=summary_path))
    return 0 if export_result.status.has_success else 1
