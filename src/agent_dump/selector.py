"""
Session selection utilities
"""

import sys
from typing import Any

import inquirer


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
        description = f"{session['created_formatted']} | {session['id']}"
        choices.append((description, session))

    questions = [
        inquirer.Checkbox(
            "sessions",
            message="选择要导出的会话:",
            choices=choices,
            default=[],
        )
    ]

    try:
        answers = inquirer.prompt(questions)
        selected = answers.get("sessions", []) if answers else []
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作，退出。")
        return []

    return selected


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
