"""
Session selection utilities
"""

from datetime import datetime, timedelta
import sys

import questionary
from questionary import Choice, Style

from agent_dump.agents.base import BaseAgent, Session


def is_terminal() -> bool:
    """Check if running in a terminal"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def get_time_group(session: Session) -> str:
    """Get time group for a session"""
    from datetime import timezone

    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    session_time = session.created_at

    if isinstance(session_time, (int, float)):
        # Assume milliseconds if large number
        if session_time > 1e10:
            session_time = datetime.fromtimestamp(session_time / 1000, tz=timezone.utc)
        else:
            session_time = datetime.fromtimestamp(session_time, tz=timezone.utc)
    elif session_time.tzinfo is None:
        # Convert naive datetime to UTC
        session_time = session_time.replace(tzinfo=timezone.utc)

    if session_time >= today:
        return "今天"
    elif session_time >= yesterday:
        return "昨天"
    elif session_time >= week_ago:
        return "本周"
    elif session_time >= month_ago:
        return "本月"
    else:
        return "更早"


def group_sessions(sessions: list[Session]) -> dict[str, list[Session]]:
    """Group sessions by time periods"""
    groups: dict[str, list[Session]] = {}

    for session in sessions:
        group = get_time_group(session)
        if group not in groups:
            groups[group] = []
        groups[group].append(session)

    # Define order
    order = ["今天", "昨天", "本周", "本月", "更早", "未知时间"]
    ordered_groups = {}
    for key in order:
        if key in groups:
            ordered_groups[key] = groups[key]

    return ordered_groups


def _get_agent_session_count(
    agent: BaseAgent, days: int, session_counts: dict[str, int] | None = None
) -> int:
    """Get session count for an agent, optionally from precomputed counts."""
    if session_counts is not None:
        return session_counts.get(agent.name, 0)

    sessions = agent.get_sessions(days=days)
    return len(sessions)


def select_agent_interactive(
    agents: list[BaseAgent], days: int = 7, session_counts: dict[str, int] | None = None
) -> BaseAgent | None:
    """Let user select an agent tool interactively"""
    if not agents:
        print("没有可用的 Agent Tools。")
        return None

    if not is_terminal():
        return select_agent_simple(agents, days=days, session_counts=session_counts)

    choices = []
    for agent in agents:
        count = _get_agent_session_count(agent, days=days, session_counts=session_counts)
        label = f"{agent.display_name} ({count} 个会话)"
        choices.append(questionary.Choice(title=label, value=agent))

    custom_style = Style(
        [
            ("qmark", "fg:#673ab7 bold"),
            ("question", "bold"),
            ("answer", "fg:#f44336 bold"),
            ("pointer", "fg:#673ab7 bold"),
            ("highlighted", "noreverse"),
            ("selected", "noreverse"),
            ("separator", "fg:#cc5454"),
            ("instruction", ""),
            ("text", ""),
        ]
    )

    q = questionary.select(
        "选择要导出的 Agent Tool:",
        choices=choices,
        style=custom_style,
        instruction="\n↑↓ 移动  |  回车 选择  |  q 退出",
    )

    if q.application.key_bindings:
        q.application.key_bindings.add("q")(lambda event: event.app.exit(result=None))  # type: ignore
        q.application.key_bindings.add("Q")(lambda event: event.app.exit(result=None))  # type: ignore

    try:
        selected = q.ask()
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作，退出。")
        return None

    return selected


def select_agent_simple(
    agents: list[BaseAgent], days: int = 7, session_counts: dict[str, int] | None = None
) -> BaseAgent | None:
    """Simple agent selection for non-terminal environments"""
    print("可用的 Agent Tools:")
    print("-" * 80)
    for i, agent in enumerate(agents, 1):
        count = _get_agent_session_count(agent, days=days, session_counts=session_counts)
        print(f"{i}. {agent.display_name} ({count} 个会话)")
    print()

    print("选择 Agent Tool 编号:")
    try:
        selection = input("> ").strip()
    except EOFError:
        print("\n⚠️  No input provided. Exiting.")
        return None

    try:
        idx = int(selection) - 1
        if 0 <= idx < len(agents):
            return agents[idx]
        else:
            print(f"⚠️  Invalid selection: {selection}")
            return None
    except ValueError:
        print("⚠️  Invalid input. Please enter a number.")
        return None


def select_sessions_interactive(sessions: list[Session], agent: BaseAgent) -> list[Session]:
    """Let user select sessions interactively with time grouping"""
    if not sessions:
        print("No sessions found in the specified time range.")
        return []

    if not is_terminal():
        return select_sessions_simple(sessions, agent)

    # Group sessions by time
    groups = group_sessions(sessions)

    choices = []

    for group_name, group_sessions_list in groups.items():
        # Add separator for group
        choices.append(Choice(title=f"─── {group_name} ({len(group_sessions_list)} 个) ───", disabled="分组标题"))

        # Add sessions in this group
        for session in group_sessions_list:
            label = agent.get_formatted_title(session)
            uri = agent.get_session_uri(session)
            choices.append(questionary.Choice(title=f"  {label} {uri}", value=session))

    custom_style = Style(
        [
            ("qmark", "fg:#673ab7 bold"),
            ("question", "bold"),
            ("answer", "fg:#f44336 bold"),
            ("pointer", "fg:#673ab7 bold"),
            ("highlighted", "noreverse"),
            ("selected", "noreverse"),
            ("separator", "fg:#cc5454"),
            ("instruction", ""),
            ("text", ""),
            ("disabled", "fg:#666666 italic"),
        ]
    )

    q = questionary.checkbox(
        "选择要导出的会话:",
        choices=choices,
        style=custom_style,
        instruction="\n↑↓ 移动  |  空格 选择/取消  |  回车 确认  |  q 退出",
    )

    if q.application.key_bindings:
        q.application.key_bindings.add("q")(lambda event: event.app.exit(result=None))  # type: ignore
        q.application.key_bindings.add("Q")(lambda event: event.app.exit(result=None))  # type: ignore

    try:
        selected = q.ask()
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作，退出。")
        return []

    return selected or []


def select_sessions_simple(sessions: list[Session], agent: BaseAgent) -> list[Session]:
    """Simple selection for non-terminal environments"""
    # Group sessions for display
    groups = group_sessions(sessions)

    print("Available sessions:")
    print("-" * 80)

    idx = 1
    session_map = {}

    for group_name, group_sessions_list in groups.items():
        print(f"\n[{group_name}] ({len(group_sessions_list)} 个)")
        for session in group_sessions_list:
            title = agent.get_formatted_title(session)
            uri = agent.get_session_uri(session)
            print(f"{idx}. {title} {uri}")
            session_map[idx] = session
            idx += 1

    print()
    print("Enter session numbers to export (comma-separated, e.g., '1,3,5' or 'all'):")
    try:
        selection = input("> ").strip()
    except EOFError:
        print("\n⚠️  No input provided. Exiting.")
        return []

    if selection.lower() == "all":
        return sessions

    try:
        indices = [int(x.strip()) for x in selection.split(",")]
        selected = []
        for num in indices:
            if num in session_map:
                selected.append(session_map[num])
            else:
                print(f"⚠️  Invalid selection: {num}")
        return selected
    except ValueError:
        print("⚠️  Invalid input. Please enter numbers separated by commas.")
        return []
