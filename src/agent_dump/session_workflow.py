from collections.abc import Callable
from typing import Protocol

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import (
    build_no_agents_found_diagnostic,
    collect_query_matches,
    collect_search_matches,
    display_search_results,
    display_sessions_list,
    export_sessions_for_formats,
    print_diagnostic,
    render_agent_search_roots,
    render_query_summary,
    resolve_output_base_dir,
    warn_list_ignored_options,
)
from agent_dump.command_plan import CommandMode, SessionOperation
from agent_dump.diagnostics import root_not_found
from agent_dump.i18n import Keys, i18n
from agent_dump.query_filter import QuerySpec
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import safe_display_text


class ExportConfigLike(Protocol):
    @property
    def output(self) -> str: ...


def handle_session_modes(
    operation: SessionOperation,
    *,
    export_config: ExportConfigLike,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
) -> int | None:
    print("🚀 Agent Session Exporter\n")
    print("=" * 60 + "\n")

    scanner = scanner_factory()
    query_spec = operation.query_spec

    available_agents = scanner.get_available_agents()

    if not available_agents:
        # 退 1 而不是 None：这里走的是诊断通道（错误语义），而 --stats / --reindex /
        # URI 模式在同一条件下已经退 1。约定见 README 的 Exit Codes 一节。
        print_diagnostic(build_no_agents_found_diagnostic(scanner))
        return 1

    if query_spec and query_spec.agent_names:
        available_agents = [agent for agent in available_agents if agent.name in query_spec.agent_names]
        if not available_agents:
            print_diagnostic(
                root_not_found(
                    i18n.t(Keys.DIAG_NO_PROVIDER_IN_SCOPE),
                    searched_roots=render_agent_search_roots(scanner.agents),
                    details=(f"query providers: {','.join(sorted(query_spec.agent_names))}",),
                    next_steps=(
                        i18n.t(Keys.DIAG_STEP_CONFIRM_PROVIDERS_HAVE_DATA),
                        i18n.t(Keys.DIAG_STEP_WIDEN_PROVIDERS),
                    ),
                )
            )
            return 0 if operation.mode is CommandMode.LIST else 1

    if operation.is_search and query_spec is not None:
        warn_list_ignored_options(operation.output_specified, operation.format_specified)
        print(
            render_terminal_message(
                Keys.SEARCH_HEADER,
                days=operation.days,
                query=render_query_summary(query_spec),
            )
        )
        print("-" * 60)
        display_search_results(
            collect_search_matches(available_agents, days=operation.days, spec=query_spec, scanner=scanner)
        )
        print("\n" + "=" * 60)
        return 0

    matched_sessions_by_agent: dict[str, list[Session]] = {}
    if query_spec:
        matched_sessions_by_agent = collect_query_matches(
            available_agents,
            days=operation.days,
            spec=query_spec,
            scanner=scanner,
        )

    if operation.mode is CommandMode.LIST:
        return _handle_list_mode(
            operation,
            scanner=scanner,
            query_spec=query_spec,
            matched_sessions_by_agent=matched_sessions_by_agent,
            available_agents=available_agents,
        )

    return _handle_interactive_mode(
        operation,
        scanner=scanner,
        query_spec=query_spec,
        matched_sessions_by_agent=matched_sessions_by_agent,
        available_agents=available_agents,
        export_config=export_config,
    )


def _handle_list_mode(
    operation: SessionOperation,
    *,
    scanner: AgentScanner,
    query_spec: QuerySpec | None,
    matched_sessions_by_agent: dict[str, list[Session]],
    available_agents: list[BaseAgent],
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
        else scanner.get_sessions(operation.days, agents=available_agents)
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
    operation: SessionOperation,
    *,
    scanner: AgentScanner,
    query_spec: QuerySpec | None,
    matched_sessions_by_agent: dict[str, list[Session]],
    available_agents: list[BaseAgent],
    export_config: ExportConfigLike,
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
        sessions_by_agent = {
            agent.name: sessions for agent, sessions in scanner.get_sessions(operation.days, agents=available_agents)
        }

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

    output_base_dirs = {
        output_format: resolve_output_base_dir(
            cli_output=operation.output,
            output_specified=operation.output_specified,
            export_output=export_config.output,
            output_format=output_format,
        )
        for output_format in operation.output_formats
    }
    primary_output_format = operation.output_formats[0] if operation.output_formats else "json"
    output_base_dir = output_base_dirs.get(
        primary_output_format,
        resolve_output_base_dir(
            cli_output=operation.output,
            output_specified=operation.output_specified,
            export_output=export_config.output,
            output_format=primary_output_format,
        ),
    )
    export_result = export_sessions_for_formats(
        selected_agent,
        selected_sessions,
        list(operation.output_formats),
        output_base_dir,
        output_base_dirs=output_base_dirs,
    )

    summary_paths = sorted({str(path.parent) for path in export_result.exported_paths})
    summary_path = ", ".join(summary_paths) if summary_paths else f"{output_base_dir}/{selected_agent.name}"
    print(render_terminal_message(Keys.EXPORT_SUMMARY, count=len(export_result), path=summary_path))
    return 0 if export_result.had_success else 1
