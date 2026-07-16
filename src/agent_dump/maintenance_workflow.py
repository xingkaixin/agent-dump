import argparse
from collections.abc import Callable

from agent_dump.agent_registry import AGENT_REGISTRATIONS, AgentRegistration
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.cli_shared import (
    VALID_FORMATS,
    apply_query_filter,
    build_no_agents_found_diagnostic,
    group_sessions_by_time,
    print_diagnostic,
    render_agent_search_roots,
)
from agent_dump.diagnostics import invalid_query_or_uri, root_not_found
from agent_dump.i18n import Keys, i18n
from agent_dump.query_filter import QuerySpec, parse_query
from agent_dump.scanner import AgentScanner
from agent_dump.search_index import SearchIndex


def handle_providers_mode(
    *,
    registrations: tuple[AgentRegistration, ...] | None = None,
) -> int:
    """Render provider capabilities without scanning session data."""
    effective_registrations = registrations if registrations is not None else AGENT_REGISTRATIONS
    provider_rows = []
    print(i18n.t(Keys.PROVIDERS_HEADER))
    print()
    print(i18n.t(Keys.PROVIDERS_TABLE_HEADER))
    print("--- | --- | --- | --- | --- | ---")

    for registration in effective_registrations:
        agent = registration.factory()
        root_states = tuple((root, root.path.exists()) for root in agent.get_search_roots())
        existing_roots = sum(exists for _, exists in root_states)
        supported_formats = sorted(VALID_FORMATS - agent.unsupported_uri_formats)
        unsupported_formats = sorted(agent.unsupported_uri_formats)
        has_keyword_fast_path = type(agent).filter_sessions_by_keyword is not BaseAgent.filter_sessions_by_keyword
        provider_rows.append((registration, root_states))
        print_row = i18n.t(
            Keys.PROVIDERS_ROW,
            provider=registration.display_name,
            uri=", ".join(f"{scheme}://" for scheme in registration.uri_schemes),
            formats=", ".join(supported_formats),
            keyword=i18n.t(Keys.PROVIDERS_YES if has_keyword_fast_path else Keys.PROVIDERS_NO),
            roots=i18n.t(Keys.PROVIDERS_ROOT_COUNT, existing=existing_roots, total=len(root_states)),
            unsupported=", ".join(unsupported_formats) or i18n.t(Keys.PROVIDERS_NONE),
        )
        print(print_row)

    print()
    print(i18n.t(Keys.PROVIDERS_SEARCH_ROOTS))
    for registration, root_states in provider_rows:
        print(f"{registration.display_name}:")
        if not root_states:
            print(i18n.t(Keys.PROVIDERS_ROOT_NONE))
            continue
        for root, exists in root_states:
            status_key = Keys.PROVIDERS_ROOT_EXISTS if exists else Keys.PROVIDERS_ROOT_MISSING
            print(i18n.t(Keys.PROVIDERS_ROOT_ROW, status=i18n.t(status_key), label=root.label, path=root.path))

    return 0


def handle_stats_mode(
    args: argparse.Namespace,
    *,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
) -> int:
    scanner = scanner_factory()
    available_agents = scanner.get_available_agents()

    if not available_agents:
        print_diagnostic(build_no_agents_found_diagnostic(scanner))
        return 1

    query_spec: QuerySpec | None = None
    if args.query:
        valid_agents = {agent.name for agent in scanner.agents}
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
            return 0

    all_sessions: list[tuple[BaseAgent, Session]] = []
    for agent in available_agents:
        sessions = agent.get_sessions(days=args.days)
        if query_spec is not None:
            sessions = apply_query_filter(agent, sessions, query_spec)
        for session in sessions:
            all_sessions.append((agent, session))

    if not all_sessions:
        print(i18n.t(Keys.STATS_NO_SESSIONS, days=args.days))
        return 0

    total_sessions = len(all_sessions)
    total_messages = 0
    agent_stats: dict[str, dict[str, int]] = {}

    for agent, session in all_sessions:
        agent_name = agent.display_name
        if agent_name not in agent_stats:
            agent_stats[agent_name] = {"sessions": 0, "messages": 0}
        agent_stats[agent_name]["sessions"] += 1

        message_count = session.metadata.get("message_count")
        if isinstance(message_count, int):
            agent_stats[agent_name]["messages"] += message_count
            total_messages += message_count

    print(i18n.t(Keys.STATS_HEADER, days=args.days))
    print()
    print(i18n.t(Keys.STATS_TOTAL_SESSIONS, count=total_sessions))
    if total_messages > 0:
        print(i18n.t(Keys.STATS_TOTAL_MESSAGES, count=total_messages))
    print()

    print(i18n.t(Keys.STATS_BY_AGENT))
    for name in sorted(agent_stats):
        stats = agent_stats[name]
        if total_messages > 0:
            print(i18n.t(Keys.STATS_AGENT_ROW, name=name, sessions=stats["sessions"], messages=stats["messages"]))
        else:
            print(f"  {name}: {stats['sessions']} {i18n.t(Keys.SESSION_COUNT_SUFFIX)}")
    print()

    grouped = group_sessions_by_time([session for _, session in all_sessions])
    if grouped:
        print(i18n.t(Keys.STATS_BY_TIME))
        for label, sessions in grouped.items():
            print(i18n.t(Keys.STATS_TIME_ROW, label=label, count=len(sessions)))

    return 0


def handle_reindex_mode(
    args: argparse.Namespace,
    *,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
    search_index_factory: Callable[[], SearchIndex] = SearchIndex,
) -> int:
    scanner = scanner_factory()
    available_agents = scanner.get_available_agents()

    if not available_agents:
        print_diagnostic(build_no_agents_found_diagnostic(scanner))
        return 1

    index = search_index_factory()
    if not index.is_available:
        print(i18n.t(Keys.SEARCH_INDEX_NOT_AVAILABLE))
        return 1

    print(i18n.t(Keys.REINDEX_START))
    print()

    total_indexed = 0
    for agent in available_agents:
        sessions = agent.get_sessions(days=args.days)
        if not sessions:
            continue
        added = index.rebuild(agent, sessions)
        total_indexed += added
        print(i18n.t(Keys.REINDEX_AGENT_DONE, agent=agent.display_name, count=added))

    print()
    print(i18n.t(Keys.REINDEX_DONE, count=total_indexed))
    return 0
