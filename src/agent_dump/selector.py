"""
Session selection utilities
"""

from datetime import datetime, timedelta
import sys

import questionary
from questionary import Choice, Style

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.i18n import Keys, i18n
from agent_dump.rendering import format_session_metadata_summary
from agent_dump.text_safety import safe_display_text
from agent_dump.time_utils import get_local_timezone, to_local_datetime


def is_terminal() -> bool:
    """Check if running in a terminal"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def get_time_group(session: Session) -> str:
    """Get time group for a session"""
    local_tz = get_local_timezone()
    now = datetime.now(local_tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    session_time = to_local_datetime(session.created_at, local_tz)

    if session_time >= today:
        return i18n.t(Keys.TIME_TODAY)
    elif session_time >= yesterday:
        return i18n.t(Keys.TIME_YESTERDAY)
    elif session_time >= week_ago:
        return i18n.t(Keys.TIME_THIS_WEEK)
    elif session_time >= month_ago:
        return i18n.t(Keys.TIME_THIS_MONTH)
    else:
        return i18n.t(Keys.TIME_OLDER)


def group_sessions(sessions: list[Session]) -> dict[str, list[Session]]:
    """Group sessions by time periods"""
    groups: dict[str, list[Session]] = {}

    for session in sessions:
        group = get_time_group(session)
        if group not in groups:
            groups[group] = []
        groups[group].append(session)

    # Define order
    order = [
        i18n.t(Keys.TIME_TODAY),
        i18n.t(Keys.TIME_YESTERDAY),
        i18n.t(Keys.TIME_THIS_WEEK),
        i18n.t(Keys.TIME_THIS_MONTH),
        i18n.t(Keys.TIME_OLDER),
        i18n.t(Keys.TIME_UNKNOWN),
    ]
    ordered_groups = {}
    for key in order:
        if key in groups:
            ordered_groups[key] = groups[key]

    return ordered_groups


def select_agent_interactive(agents: list[BaseAgent], session_counts: dict[str, int]) -> BaseAgent | None:
    """Let user select an agent tool interactively.

    session_counts 是必填的：selector 属于 UI 层，不得自己去扫 provider
    （AGENTS.md §1.4）。调用方本来就要扫一次，把计数传进来即可。
    """
    if not agents:
        print(i18n.t(Keys.NO_AGENTS_FOUND))
        return None

    if not is_terminal():
        return select_agent_simple(agents, session_counts)

    choices = []
    for agent in agents:
        count = session_counts.get(agent.name, 0)
        label = f"{agent.display_name} ({count} {i18n.t(Keys.SESSION_COUNT_SUFFIX)})"
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
        i18n.t(Keys.SELECT_AGENT_PROMPT),
        choices=choices,
        style=custom_style,
        instruction=i18n.t(Keys.SELECT_INSTRUCTION),
    )

    if q.application.key_bindings:
        q.application.key_bindings.add("q")(lambda event: event.app.exit(result=None))  # type: ignore
        q.application.key_bindings.add("Q")(lambda event: event.app.exit(result=None))  # type: ignore

    try:
        selected = q.ask()
    except KeyboardInterrupt:
        print("\n" + i18n.t(Keys.USER_CANCELLED))
        return None

    return selected


def select_agent_simple(agents: list[BaseAgent], session_counts: dict[str, int]) -> BaseAgent | None:
    """Simple agent selection for non-terminal environments"""
    print(i18n.t(Keys.AVAILABLE_AGENTS))
    print("-" * 80)
    for i, agent in enumerate(agents, 1):
        count = session_counts.get(agent.name, 0)
        print(f"{i}. {agent.display_name} ({count} {i18n.t(Keys.SESSION_COUNT_SUFFIX)})")
    print()

    print(i18n.t(Keys.SELECT_AGENT_NUMBER))
    try:
        selection = input("> ").strip()
    except EOFError:
        print("\n" + i18n.t(Keys.NO_INPUT_EXITING))
        return None

    try:
        idx = int(selection) - 1
        if 0 <= idx < len(agents):
            return agents[idx]
        else:
            print(i18n.t(Keys.INVALID_SELECTION, selection=selection))
            return None
    except ValueError:
        print(i18n.t(Keys.INVALID_INPUT_NUMBER))
        return None


def select_sessions_interactive(
    sessions: list[Session], agent: BaseAgent, show_metadata_summary: bool = True
) -> list[Session]:
    """Let user select sessions interactively with time grouping"""
    if not sessions:
        print(i18n.t(Keys.NO_SESSIONS_IN_RANGE))
        return []

    if not is_terminal():
        return select_sessions_simple(sessions, agent, show_metadata_summary=show_metadata_summary)

    # Group sessions by time
    groups = group_sessions(sessions)

    choices = []

    for group_name, group_sessions_list in groups.items():
        # Add separator for group
        choices.append(
            Choice(
                title=i18n.t(Keys.GROUP_TITLE, group_name=group_name, count=len(group_sessions_list)),
                disabled=i18n.t(Keys.GROUP_HEADER_DISABLED_HINT),
            )
        )

        # Add sessions in this group
        for session in group_sessions_list:
            # 标题、summary、URI 全部来自第三方 Session；先逐个净化成单行，再由这里
            # 加入有意的换行。对拼好的整块调 safe_display_text 会把布局一起压平。
            label = safe_display_text(agent.get_formatted_title(session))
            if show_metadata_summary:
                summary = safe_display_text(format_session_metadata_summary(agent, session))
                title = f"  {label}\n    {summary}"
            else:
                uri = safe_display_text(agent.get_session_uri(session))
                title = f"  {label} {uri}"
            choices.append(questionary.Choice(title=title, value=session))

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
        i18n.t(Keys.SELECT_SESSIONS_PROMPT),
        choices=choices,
        style=custom_style,
        instruction=i18n.t(Keys.CHECKBOX_INSTRUCTION),
    )

    if q.application.key_bindings:
        q.application.key_bindings.add("q")(lambda event: event.app.exit(result=None))  # type: ignore
        q.application.key_bindings.add("Q")(lambda event: event.app.exit(result=None))  # type: ignore

    try:
        selected = q.ask()
    except KeyboardInterrupt:
        print("\n" + i18n.t(Keys.USER_CANCELLED))
        return []

    return selected or []


def select_sessions_simple(
    sessions: list[Session], agent: BaseAgent, show_metadata_summary: bool = True
) -> list[Session]:
    """Simple selection for non-terminal environments"""
    # Group sessions for display
    groups = group_sessions(sessions)

    print(i18n.t(Keys.AVAILABLE_SESSIONS))
    print("-" * 80)

    idx = 1
    session_map = {}

    for group_name, group_sessions_list in groups.items():
        print(f"\n[{group_name}] ({len(group_sessions_list)} {i18n.t(Keys.SESSION_COUNT_SUFFIX)})")
        for session in group_sessions_list:
            title = safe_display_text(agent.get_formatted_title(session))
            if show_metadata_summary:
                print(f"{idx}. {title}")
                print(f"    {safe_display_text(format_session_metadata_summary(agent, session))}")
            else:
                uri = safe_display_text(agent.get_session_uri(session))
                print(f"{idx}. {title} {uri}")
            session_map[idx] = session
            idx += 1

    print()
    print(i18n.t(Keys.ENTER_SESSION_NUMBERS))
    try:
        selection = input("> ").strip()
    except EOFError:
        print("\n" + i18n.t(Keys.NO_INPUT_EXITING))
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
                print(i18n.t(Keys.INVALID_SELECTION, selection=num))
        return selected
    except ValueError:
        print(i18n.t(Keys.INVALID_INPUT_NUMBERS))
        return []
