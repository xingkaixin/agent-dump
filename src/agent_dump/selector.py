"""
Session selection utilities
"""

import sys

import questionary
from questionary import Style

from agent_dump.agents.base import BaseAgent, Session


def is_terminal() -> bool:
    """Check if running in a terminal"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def select_agent_interactive(agents: list[BaseAgent]) -> BaseAgent | None:
    """Let user select an agent tool interactively"""
    if not agents:
        print("没有可用的 Agent Tools。")
        return None

    if not is_terminal():
        return select_agent_simple(agents)

    choices = []
    for agent in agents:
        # Get session count
        sessions = agent.scan()
        label = f"{agent.display_name} ({len(sessions)} 个会话)"
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


def select_agent_simple(agents: list[BaseAgent]) -> BaseAgent | None:
    """Simple agent selection for non-terminal environments"""
    print("可用的 Agent Tools:")
    print("-" * 80)
    for i, agent in enumerate(agents, 1):
        sessions = agent.scan()
        print(f"{i}. {agent.display_name} ({len(sessions)} 个会话)")
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
    """Let user select sessions interactively"""
    if not sessions:
        print("No sessions found in the specified time range.")
        return []

    if not is_terminal():
        return select_sessions_simple(sessions, agent)

    choices = []
    for session in sessions:
        label = agent.get_formatted_title(session)
        choices.append(questionary.Choice(title=label, value=session))

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
    print("Available sessions:")
    print("-" * 80)
    for i, session in enumerate(sessions, 1):
        title = agent.get_formatted_title(session)
        print(f"{i}. {title}")
        print(f"   ID: {session.id}")
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
        indices = [int(x.strip()) - 1 for x in selection.split(",")]
        selected = []
        for idx in indices:
            if 0 <= idx < len(sessions):
                selected.append(sessions[idx])
            else:
                print(f"⚠️  Invalid selection: {idx + 1}")
        return selected
    except ValueError:
        print("⚠️  Invalid input. Please enter numbers separated by commas.")
        return []
