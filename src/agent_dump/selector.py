"""
Session selection utilities
"""

import sys
from typing import Any

import questionary
from questionary import Style


def is_terminal() -> bool:
    """Check if running in a terminal"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def select_sessions_interactive(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Let user select sessions interactively"""
    if not sessions:
        print("No sessions found in the specified time range.")
        return []

    if not is_terminal():
        return select_sessions_simple(sessions)

    choices = []
    for session in sessions:
        title = session["title"][:60] + ("..." if len(session["title"]) > 60 else "")
        time_str = session["created_formatted"]
        label = f"{title} ({time_str})"
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

    q.application.key_bindings.add("q")(lambda event: event.app.exit(result=None))
    q.application.key_bindings.add("Q")(lambda event: event.app.exit(result=None))

    try:
        selected = q.ask()
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作，退出。")
        return []

    return selected or []


def select_sessions_simple(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Simple selection for non-terminal environments"""
    print("Available sessions:")
    print("-" * 80)
    for i, session in enumerate(sessions, 1):
        print(f"{i}. {session['title'][:60]}")
        print(f"   {session['created_formatted']} | {session['id']}")
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
