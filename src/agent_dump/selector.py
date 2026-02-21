"""
Session selection utilities
"""

import sys
from typing import Any

import questionary


def is_terminal() -> bool:
    """Check if running in a terminal"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def select_sessions_interactive(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Let user select sessions interactively"""
    if not sessions:
        print("No sessions found in the specified time range.")
        return []

    # If not in terminal, use simple selection
    if not is_terminal():
        return select_sessions_simple(sessions)

    # Prepare choices for questionary
    choices = []
    for session in sessions:
        # Format: Title (Date) - ID
        label = f"{session['title'][:60]}{'...' if len(session['title']) > 60 else ''}"
        description = f"{session['created_formatted']} | {session['id']}"

        choices.append(questionary.Choice(title=label, value=session, description=description))

    # Show interactive checkbox
    selected = questionary.checkbox(
        "选择要导出的会话 (空格选择/取消, 回车确认):",
        choices=choices,
        instruction="\n使用 ↑↓ 移动, 空格 选择/取消, 回车 确认导出",
    ).ask()

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
