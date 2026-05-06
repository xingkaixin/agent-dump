import argparse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import DiagnosticError, invalid_query_or_uri, root_not_found
from agent_dump.i18n import Keys, i18n
from agent_dump.query_filter import QuerySpec
from agent_dump.scanner import AgentScanner


@dataclass(frozen=True)
class MaintenanceModeDeps:
    scanner_factory: Callable[[], AgentScanner]
    search_index_factory: Callable[[], Any]
    parse_query: Callable[..., QuerySpec | None]
    apply_query_filter: Callable[[BaseAgent, list[Session], QuerySpec | None], list[Session]]
    group_sessions_by_time: Callable[[list[Session]], dict[str, list[Session]]]
    print_diagnostic: Callable[[DiagnosticError], None]
    build_no_agents_found_diagnostic: Callable[[AgentScanner], DiagnosticError]
    render_agent_search_roots: Callable[..., tuple[str, ...]]


def handle_stats_mode(args: argparse.Namespace, *, deps: MaintenanceModeDeps) -> int:
    scanner = deps.scanner_factory()
    available_agents = scanner.get_available_agents()

    if not available_agents:
        deps.print_diagnostic(deps.build_no_agents_found_diagnostic(scanner))
        return 1

    query_spec: QuerySpec | None = None
    if args.query:
        valid_agents = {agent.name for agent in scanner.agents}
        try:
            query_spec = deps.parse_query(args.query, valid_agents=valid_agents)
        except ValueError as e:
            deps.print_diagnostic(
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
            deps.print_diagnostic(
                root_not_found(
                    "查询范围内没有可用 provider。",
                    searched_roots=deps.render_agent_search_roots(scanner.agents),
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
            sessions = deps.apply_query_filter(agent, sessions, query_spec)
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

    grouped = deps.group_sessions_by_time([session for _, session in all_sessions])
    if grouped:
        print(i18n.t(Keys.STATS_BY_TIME))
        for label, sessions in grouped.items():
            print(i18n.t(Keys.STATS_TIME_ROW, label=label, count=len(sessions)))

    return 0


def handle_reindex_mode(args: argparse.Namespace, *, deps: MaintenanceModeDeps) -> int:
    scanner = deps.scanner_factory()
    available_agents = scanner.get_available_agents()

    if not available_agents:
        deps.print_diagnostic(deps.build_no_agents_found_diagnostic(scanner))
        return 1

    index = deps.search_index_factory()
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
