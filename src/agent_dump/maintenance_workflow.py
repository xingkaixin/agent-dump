from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from agent_dump.agent_registry import AGENT_REGISTRATIONS, AgentRegistration
from agent_dump.agents.base import BaseAgent, MessageCountCompleteness, MessageCountFact, Session
from agent_dump.cli_shared import (
    build_no_agents_found_diagnostic,
    collect_query_matches,
    discover_query_sessions,
    print_diagnostic,
    scope_session_groups_by_provider,
)
from agent_dump.command_plan import ReindexOperation, StatsOperation
from agent_dump.diagnostics import print_recoverable_diagnostic
from agent_dump.i18n import Keys, i18n
from agent_dump.output_formats import VALID_FORMATS
from agent_dump.scanner import AgentScanner
from agent_dump.search_index import SearchIndex
from agent_dump.session_time_groups import group_sessions_by_age
from agent_dump.terminal_output import render_terminal_message
from agent_dump.text_safety import safe_display_text
from agent_dump.time_utils import get_local_timezone


@dataclass
class _MessageStats:
    sessions: int = 0
    known_messages: int = 0
    unknown_sessions: int = 0

    def add(self, fact: MessageCountFact) -> None:
        self.sessions += 1
        if fact.completeness is MessageCountCompleteness.UNKNOWN:
            self.unknown_sessions += 1
            return
        self.known_messages += fact.exact_value


def group_sessions_by_time(sessions: list[Session]) -> dict[str, list[Session]]:
    local_tz = get_local_timezone()
    groups = group_sessions_by_age(sessions, now=datetime.now(local_tz), local_tz=local_tz)
    return {i18n.t(group.value): group_sessions for group, group_sessions in groups.items()}


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
    print("--- | --- | --- | --- | ---")

    for registration in effective_registrations:
        agent = registration.factory()
        root_states = tuple((root, root.path.exists()) for root in agent.get_search_roots())
        existing_roots = sum(exists for _, exists in root_states)
        supported_formats = sorted(VALID_FORMATS - agent.unsupported_uri_formats)
        unsupported_formats = sorted(agent.unsupported_uri_formats)
        provider_rows.append((registration, root_states))
        print_row = render_terminal_message(
            Keys.PROVIDERS_ROW,
            provider=registration.display_name,
            uri=", ".join(f"{scheme}://" for scheme in registration.uri_schemes),
            formats=", ".join(supported_formats),
            roots=i18n.t(Keys.PROVIDERS_ROOT_COUNT, existing=existing_roots, total=len(root_states)),
            unsupported=", ".join(unsupported_formats) or i18n.t(Keys.PROVIDERS_NONE),
        )
        print(print_row)

    print()
    print(i18n.t(Keys.PROVIDERS_SEARCH_ROOTS))
    for registration, root_states in provider_rows:
        print(f"{safe_display_text(registration.display_name)}:")
        if not root_states:
            print(i18n.t(Keys.PROVIDERS_ROOT_NONE))
            continue
        for root, exists in root_states:
            status_key = Keys.PROVIDERS_ROOT_EXISTS if exists else Keys.PROVIDERS_ROOT_MISSING
            print(
                render_terminal_message(
                    Keys.PROVIDERS_ROOT_ROW,
                    status=i18n.t(status_key),
                    label=root.label,
                    path=root.path,
                )
            )

    return 0


def handle_stats_mode(
    operation: StatsOperation,
    *,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
) -> int:
    scanner = scanner_factory()
    query_spec = operation.query_spec
    scanned_sessions = discover_query_sessions(scanner, operation.days, query_spec)

    if not scanned_sessions and (query_spec is None or query_spec.agent_names is None):
        print_diagnostic(build_no_agents_found_diagnostic(scanner))
        return 1

    scanned_sessions, scope_error = scope_session_groups_by_provider(
        scanned_sessions,
        agent_names=query_spec.agent_names if query_spec is not None else None,
        all_agents=scanner.agents,
    )
    if scope_error is not None:
        print_diagnostic(scope_error)
        return 0
    available_agents = [agent for agent, _ in scanned_sessions]

    sessions_by_agent = (
        collect_query_matches(
            scanned_sessions,
            spec=query_spec,
        )
        if query_spec is not None
        else None
    )
    scanned_sessions = (
        [(agent, sessions_by_agent.get(agent.name, [])) for agent in available_agents]
        if sessions_by_agent is not None
        else scanned_sessions
    )

    all_sessions: list[tuple[BaseAgent, Session]] = []
    for agent, sessions in scanned_sessions:
        for session in sessions:
            all_sessions.append((agent, session))

    if not all_sessions:
        print(i18n.t(Keys.STATS_NO_SESSIONS, days=operation.days))
        return 0

    total_stats = _MessageStats()
    agent_stats: dict[str, _MessageStats] = {}

    for agent, session in all_sessions:
        agent_name = agent.display_name
        message_count = agent.get_session_facts(session).message_count
        total_stats.add(message_count)
        agent_stats.setdefault(agent_name, _MessageStats()).add(message_count)

    print(i18n.t(Keys.STATS_HEADER, days=operation.days))
    print()
    print(i18n.t(Keys.STATS_TOTAL_SESSIONS, count=total_stats.sessions))
    if total_stats.unknown_sessions:
        print(
            i18n.t(
                Keys.STATS_KNOWN_MESSAGES,
                count=total_stats.known_messages,
                unknown_sessions=total_stats.unknown_sessions,
            )
        )
    else:
        print(i18n.t(Keys.STATS_TOTAL_MESSAGES, count=total_stats.known_messages))
    print()

    print(i18n.t(Keys.STATS_BY_AGENT))
    for name in sorted(agent_stats):
        stats = agent_stats[name]
        if stats.unknown_sessions:
            print(
                render_terminal_message(
                    Keys.STATS_AGENT_ROW_WITH_UNKNOWN,
                    name=name,
                    sessions=stats.sessions,
                    messages=stats.known_messages,
                    unknown_sessions=stats.unknown_sessions,
                )
            )
        else:
            print(
                render_terminal_message(
                    Keys.STATS_AGENT_ROW,
                    name=name,
                    sessions=stats.sessions,
                    messages=stats.known_messages,
                )
            )
    print()

    grouped = group_sessions_by_time([session for _, session in all_sessions])
    if grouped:
        print(i18n.t(Keys.STATS_BY_TIME))
        for label, sessions in grouped.items():
            print(i18n.t(Keys.STATS_TIME_ROW, label=label, count=len(sessions)))

    return 0


def handle_reindex_mode(
    operation: ReindexOperation,
    *,
    scanner_factory: Callable[[], AgentScanner] = AgentScanner,
    search_index_factory: Callable[[], SearchIndex] = SearchIndex,
) -> int:
    scanner = scanner_factory()
    scanned_sessions = scanner.get_available_sessions(operation.days)
    available_agents = [agent for agent, _ in scanned_sessions]

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
    for agent, sessions in scanned_sessions:
        if not sessions:
            continue
        added = index.rebuild(agent, sessions, diagnostic_sink=print_recoverable_diagnostic)
        total_indexed += added
        print(render_terminal_message(Keys.REINDEX_AGENT_DONE, agent=agent.display_name, count=added))

    print()
    print(i18n.t(Keys.REINDEX_DONE, count=total_indexed))
    return 0
