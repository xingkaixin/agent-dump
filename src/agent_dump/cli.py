"""
Command-line interface for agent-dump
"""

import argparse
from pathlib import Path

from agent_dump.db import find_db_path, get_recent_sessions
from agent_dump.exporter import export_sessions
from agent_dump.selector import select_sessions_interactive


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Export agent sessions to JSON")
    parser.add_argument("--days", type=int, default=7, help="Number of days to look back (default: 7)")
    parser.add_argument(
        "--agent",
        type=str,
        default="opencode",
        help="Agent tool name (default: opencode)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./sessions",
        help="Output base directory (default: ./sessions)",
    )
    parser.add_argument(
        "--export",
        type=str,
        metavar="IDS",
        help="Export specific session IDs (comma-separated)",
    )
    parser.add_argument("--list", action="store_true", help="List sessions without exporting")
    args = parser.parse_args()

    print(f"🔍 {args.agent.title()} Session Exporter\n")

    # Find database
    try:
        db_path = find_db_path()
        print(f"📁 Database: {db_path}\n")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        return

    # Get recent sessions
    print(f"📊 Loading sessions from the last {args.days} days...")
    sessions = get_recent_sessions(db_path, days=args.days)
    print(f"✓ Found {len(sessions)} sessions\n")

    if not sessions:
        print("No sessions found.")
        return

    # List mode
    if args.list:
        print("Available sessions:")
        print("-" * 80)
        for i, session in enumerate(sessions, 1):
            print(f"{i}. {session['title']}")
            print(f"   Time: {session['created_formatted']}")
            print(f"   ID: {session['id']}")
            print()
        return

    # Export specific IDs
    if args.export:
        target_ids = [sid.strip() for sid in args.export.split(",")]
        selected = [s for s in sessions if s["id"] in target_ids]
        if not selected:
            print(f"❌ No sessions found with IDs: {args.export}")
            return
        print(f"✓ Selected {len(selected)} session(s) by ID\n")
    else:
        # Interactive selection
        selected = select_sessions_interactive(sessions)
        if not selected:
            print("\n⚠️  No sessions selected. Exiting.")
            return
        print(f"\n✓ Selected {len(selected)} session(s)\n")

    # Export
    output_dir = Path(args.output) / args.agent
    exported = export_sessions(db_path, selected, output_dir)
    print(f"\n✅ Successfully exported {len(exported)} session(s) to {output_dir}/")


if __name__ == "__main__":
    main()
