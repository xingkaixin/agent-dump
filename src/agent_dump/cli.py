"""
Command-line interface for agent-dump
"""

import argparse
from pathlib import Path

from agent_dump.agents.base import BaseAgent
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive


def export_sessions(agent: BaseAgent, sessions: list, output_base_dir: Path) -> list[Path]:
    """Export multiple sessions"""
    output_dir = output_base_dir / agent.name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"📤 导出 {agent.display_name} 会话...")
    exported = []
    for session in sessions:
        try:
            output_path = agent.export_session(session, output_dir)
            exported.append(output_path)
            print(f"  ✓ {session.title[:50]}... → {output_path.name}")
        except Exception as e:
            print(f"  ✗ {session.title[:50]}... → 错误: {e}")

    return exported


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Export agent sessions to JSON")
    parser.add_argument("--days", type=int, default=7, help="Number of days to look back (default: 7)")
    parser.add_argument(
        "--output",
        type=str,
        default="./sessions",
        help="Output base directory (default: ./sessions)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available sessions without exporting",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive mode to select and export sessions",
    )
    args = parser.parse_args()

    # 如果没有指定 --interactive 或 --list，但指定了 --days，则自动启用 --list
    # 如果都没有指定，显示帮助信息
    if not args.interactive and not args.list:
        if args.days != 7:  # 用户显式指定了 --days
            args.list = True
        else:
            parser.print_help()
            return

    print("🚀 Agent Session Exporter\n")
    print("=" * 60 + "\n")

    # Scan for available agents
    scanner = AgentScanner()
    available_sessions = scanner.scan()

    if not available_sessions:
        print("❌ 未找到任何可用的 Agent Tools 会话。")
        print("\n支持的 Agent Tools:")
        print("  - OpenCode: ~/.local/share/opencode/opencode.db")
        print("  - Codex: ~/.codex/sessions/{YYYY}/{MM}/{DD}/")
        print("  - Kimi: ~/.kimi/sessions/{project_id}/{session_id}/")
        print("  - Claude Code: ~/.claude/projects/{project_id}/")
        return

    # Get available agents
    available_agents = scanner.get_available_agents()

    # List mode
    if args.list:
        print("可用的 Agent Tools 和会话:")
        print("-" * 60)
        for agent in available_agents:
            sessions = available_sessions.get(agent.name, [])
            print(f"\n📁 {agent.display_name} ({len(sessions)} 个会话)")
            for session in sessions[:10]:  # Show first 10
                print(f"   • {agent.get_formatted_title(session)}")
            if len(sessions) > 10:
                print(f"   ... 还有 {len(sessions) - 10} 个会话")
        print()
        return

    # Select agent
    if len(available_agents) == 1:
        selected_agent = available_agents[0]
        print(f"自动选择: {selected_agent.display_name}\n")
    else:
        selected_agent = select_agent_interactive(available_agents)
        if not selected_agent:
            print("\n⚠️  未选择 Agent Tool，退出。")
            return
        print(f"\n已选择: {selected_agent.display_name}\n")

    # Get sessions for the selected agent
    sessions = selected_agent.get_sessions(days=args.days)

    if not sessions:
        print(f"⚠️  未找到最近 {args.days} 天内的会话。")
        return

    print(f"📊 找到 {len(sessions)} 个会话 (最近 {args.days} 天)\n")

    # Select sessions
    selected_sessions = select_sessions_interactive(sessions, selected_agent)
    if not selected_sessions:
        print("\n⚠️  未选择会话，退出。")
        return

    print(f"\n✓ 选择了 {len(selected_sessions)} 个会话\n")

    # Export
    output_base_dir = Path(args.output)
    exported = export_sessions(selected_agent, selected_sessions, output_base_dir)

    print(f"\n✅ 成功导出 {len(exported)} 个会话到 {output_base_dir}/{selected_agent.name}/")


if __name__ == "__main__":
    main()
