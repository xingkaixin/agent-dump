import argparse
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
from agent_dump.diagnostics import invalid_query_or_uri, root_not_found
from agent_dump.i18n import Keys, i18n
from agent_dump.query_filter import QuerySpec, parse_query
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive


class ExportConfigLike(Protocol):
    output: str


def handle_session_modes(
    args: argparse.Namespace,
    *,
    query_uri_spec: QuerySpec | None,
    output_specified: bool,
    format_specified: bool,
    output_formats: list[str],
    export_config: ExportConfigLike,
    print_help: Callable[[], None],
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
) -> int | None:
    if args.search:
        args.list = True

    if not args.interactive and not args.list:
        if args.days != 7 or args.query or query_uri_spec is not None:
            args.list = True
        else:
            print_help()
            return None

    print("🚀 Agent Session Exporter\n")
    print("=" * 60 + "\n")

    scanner = scanner_factory()
    valid_agents = {agent.name for agent in scanner.agents}
    if query_uri_spec is not None:
        query_spec = query_uri_spec
    else:
        try:
            query_spec = parse_query(args.query, valid_agents=valid_agents)
        except ValueError as e:
            print_diagnostic(
                invalid_query_or_uri(
                    "查询条件无效。",
                    details=(str(e),),
                    next_steps=(
                        "使用 `关键词` 或 `agent1,agent2:关键词` 格式。",
                        "如需路径作用域查询，改用 `agents://<path>?q=<keyword>&providers=<names>`。",
                    ),
                )
            )
            return 1

    if args.search:
        if query_spec is None:
            query_spec = QuerySpec(
                agent_names=None,
                keyword=args.search,
                project_path=None,
                roles=None,
                limit=None,
            )
        else:
            query_spec = QuerySpec(
                agent_names=query_spec.agent_names,
                keyword=args.search,
                project_path=query_spec.project_path,
                roles=query_spec.roles,
                limit=query_spec.limit,
            )

    available_agents = scanner.get_available_agents()

    if not available_agents:
        print_diagnostic(build_no_agents_found_diagnostic(scanner))
        return None

    if query_spec and query_spec.agent_names:
        available_agents = [agent for agent in available_agents if agent.name in query_spec.agent_names]
        if not available_agents:
            print_diagnostic(
                root_not_found(
                    "查询范围内没有可用 provider。",
                    searched_roots=render_agent_search_roots(scanner.agents),
                    details=(f"query providers: {','.join(sorted(query_spec.agent_names))}",),
                    next_steps=(
                        "确认这些 provider 在本机上确实存在会话数据。",
                        "放宽 providers 范围，或先不加 provider 过滤执行 `--list`。",
                    ),
                )
            )
            return 0 if args.list else 1

    if args.search and query_spec is not None:
        warn_list_ignored_options(output_specified, format_specified)
        print(i18n.t(Keys.SEARCH_HEADER, days=args.days, query=render_query_summary(query_spec)))
        print("-" * 60)
        display_search_results(collect_search_matches(available_agents, days=args.days, spec=query_spec))
        print("\n" + "=" * 60)
        return 0

    matched_sessions_by_agent: dict[str, list[Session]] = {}
    if query_spec:
        matched_sessions_by_agent = collect_query_matches(available_agents, days=args.days, spec=query_spec)

    if args.list:
        return _handle_list_mode(
            args,
            query_spec=query_spec,
            matched_sessions_by_agent=matched_sessions_by_agent,
            available_agents=available_agents,
            output_specified=output_specified,
            format_specified=format_specified,
        )

    return _handle_interactive_mode(
        args,
        query_spec=query_spec,
        matched_sessions_by_agent=matched_sessions_by_agent,
        available_agents=available_agents,
        output_specified=output_specified,
        output_formats=output_formats,
        export_config=export_config,
    )


def _handle_list_mode(
    args: argparse.Namespace,
    *,
    query_spec: QuerySpec | None,
    matched_sessions_by_agent: dict[str, list[Session]],
    available_agents: list[BaseAgent],
    output_specified: bool,
    format_specified: bool,
) -> int:
    warn_list_ignored_options(output_specified, format_specified)
    if query_spec:
        print(i18n.t(Keys.LIST_HEADER_FILTERED, days=args.days, query=render_query_summary(query_spec)))
    else:
        print(i18n.t(Keys.LIST_HEADER, days=args.days))
    print("-" * 60)

    show_metadata_summary = not args.no_metadata_summary
    for agent in available_agents:
        sessions = matched_sessions_by_agent.get(agent.name, []) if query_spec else agent.get_sessions(days=args.days)

        print(f"\n📁 {agent.display_name} ({len(sessions)} {i18n.t(Keys.SESSION_COUNT_SUFFIX)})")

        if sessions:
            should_quit = display_sessions_list(
                agent,
                sessions,
                page_size=max(len(sessions), 1),
                show_pagination=False,
                show_metadata_summary=show_metadata_summary,
            )
            if should_quit:
                print("\n" + "=" * 60)
                return 0
        else:
            print(i18n.t(Keys.NO_SESSIONS_IN_DAYS, days=args.days))

    print("\n" + "=" * 60)
    print(i18n.t(Keys.HINT_INTERACTIVE))
    print()
    return 0


def _handle_interactive_mode(
    args: argparse.Namespace,
    *,
    query_spec: QuerySpec | None,
    matched_sessions_by_agent: dict[str, list[Session]],
    available_agents: list[BaseAgent],
    output_specified: bool,
    output_formats: list[str],
    export_config: ExportConfigLike,
) -> int:
    interactive_agents = available_agents
    session_counts: dict[str, int] | None = None
    show_metadata_summary = not args.no_metadata_summary

    if query_spec:
        session_counts = {
            agent.name: len(matched_sessions_by_agent[agent.name])
            for agent in available_agents
            if agent.name in matched_sessions_by_agent
        }
        interactive_agents = [agent for agent in available_agents if agent.name in matched_sessions_by_agent]
        if not interactive_agents:
            print(
                i18n.t(
                    Keys.NO_SESSIONS_MATCHING_KEYWORD,
                    days=args.days,
                    query=render_query_summary(query_spec),
                )
            )
            return 1

    if len(interactive_agents) == 1:
        selected_agent = interactive_agents[0]
        print(i18n.t(Keys.AUTO_SELECT_AGENT, agent_name=selected_agent.display_name))
    else:
        selected_agent = select_agent_interactive(
            interactive_agents,
            days=args.days,
            session_counts=session_counts,
        )
        if not selected_agent:
            print("\n" + i18n.t(Keys.NO_AGENT_SELECTED))
            return 1
        print(i18n.t(Keys.AGENT_SELECTED, agent_name=selected_agent.display_name))

    if query_spec:
        sessions = matched_sessions_by_agent.get(selected_agent.name, [])
    else:
        sessions = selected_agent.get_sessions(days=args.days)

    if not sessions:
        if query_spec:
            print(i18n.t(Keys.NO_SESSIONS_MATCHING_KEYWORD, days=args.days, query=render_query_summary(query_spec)))
        else:
            print(i18n.t(Keys.NO_SESSIONS_FOUND, days=args.days))
        return 1

    if query_spec:
        print(
            i18n.t(
                Keys.SESSIONS_FOUND_FILTERED,
                count=len(sessions),
                days=args.days,
                query=render_query_summary(query_spec),
            )
        )
    else:
        print(i18n.t(Keys.SESSIONS_FOUND, count=len(sessions), days=args.days))

    if len(sessions) > 100:
        print(i18n.t(Keys.MANY_SESSIONS_WARNING, count=len(sessions)))
        print(i18n.t(Keys.MANY_SESSIONS_EXAMPLE))

    selected_sessions = select_sessions_interactive(
        sessions,
        selected_agent,
        show_metadata_summary=show_metadata_summary,
    )
    if not selected_sessions:
        print("\n" + i18n.t(Keys.NO_SESSION_SELECTED))
        return 1

    print(i18n.t(Keys.SESSIONS_SELECTED_COUNT, count=len(selected_sessions)))

    output_base_dirs = {
        output_format: resolve_output_base_dir(
            cli_output=args.output,
            output_specified=output_specified,
            export_output=export_config.output,
            output_format=output_format,
        )
        for output_format in output_formats
    }
    primary_output_format = output_formats[0] if output_formats else "json"
    output_base_dir = output_base_dirs.get(
        primary_output_format,
        resolve_output_base_dir(
            cli_output=args.output,
            output_specified=output_specified,
            export_output=export_config.output,
            output_format=primary_output_format,
        ),
    )
    exported = export_sessions_for_formats(
        selected_agent,
        selected_sessions,
        output_formats,
        output_base_dir,
        output_base_dirs=output_base_dirs,
    )

    summary_paths = sorted({str(path.parent) for path in exported})
    summary_path = ", ".join(summary_paths) if summary_paths else f"{output_base_dir}/{selected_agent.name}"
    print(i18n.t(Keys.EXPORT_SUMMARY, count=len(exported), path=summary_path))
    return 0
