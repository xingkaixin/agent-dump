"""
Command-line interface for agent-dump
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import re

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.scanner import AgentScanner
from agent_dump.selector import select_agent_interactive, select_sessions_interactive

# Valid URI schemes and their corresponding agent names
VALID_URI_SCHEMES = {
    "opencode": "opencode",
    "codex": "codex",
    "kimi": "kimi",
    "claude": "claudecode",  # claude:// maps to claudecode agent
}


def parse_uri(uri: str) -> tuple[str, str] | None:
    """
    Parse an agent session URI.
    Returns (scheme, session_id) if valid, None otherwise.
    """
    pattern = r"^([a-z]+)://(.+)$"
    match = re.match(pattern, uri)
    if not match:
        return None
    scheme, session_id = match.groups()
    if scheme not in VALID_URI_SCHEMES:
        return None
    return scheme, session_id


def find_session_by_id(scanner: AgentScanner, session_id: str) -> tuple[BaseAgent, Session] | None:
    """Find a session by ID across all available agents"""
    for agent in scanner.get_available_agents():
        # Scan all sessions (use a large days value)
        sessions = agent.get_sessions(days=3650)
        for session in sessions:
            if session.id == session_id:
                return agent, session
    return None


def render_session_text(uri: str, session_data: dict) -> str:
    """Render session data as formatted text"""
    lines = []
    lines.append("# Session Dump")
    lines.append("")
    lines.append(f"- URI: `{uri}`")
    lines.append("")

    messages = session_data.get("messages", [])
    msg_idx = 1

    for msg in messages:
        role = msg.get("role", "unknown")
        parts = msg.get("parts", [])

        # Skip tool messages
        if role == "tool":
            continue

        # Determine display name
        if role == "user":
            display_role = "User"
        elif role == "assistant":
            display_role = "Assistant"
        else:
            display_role = role.capitalize()

        # Collect content from parts
        content_parts = []
        for part in parts:
            part_type = part.get("type")
            if part_type in ("text", "reasoning"):
                text = part.get("text", "").strip()
                if text:
                    content_parts.append(text)
            # Skip tool parts and other non-text parts

        if not content_parts:
            continue

        # Add section header
        lines.append(f"## {msg_idx}. {display_role}")
        lines.append("")

        # Add content
        for content in content_parts:
            lines.append(content)
            lines.append("")

        msg_idx += 1

    return "\n".join(lines)


def format_relative_time(time_value: datetime | float) -> str:
    """Format time as relative description"""
    if isinstance(time_value, (int, float)):
        time_value = datetime.fromtimestamp(time_value)

    now = datetime.now()
    delta = now - time_value

    if delta.days == 0:
        if delta.seconds < 3600:
            minutes = delta.seconds // 60
            return f"{minutes} 分钟前" if minutes > 0 else "刚刚"
        hours = delta.seconds // 3600
        return f"{hours} 小时前"
    elif delta.days == 1:
        return "昨天"
    elif delta.days < 7:
        return f"{delta.days} 天前"
    elif delta.days < 30:
        weeks = delta.days // 7
        return f"{weeks} 周前"
    else:
        return time_value.strftime("%Y-%m-%d")


def group_sessions_by_time(sessions: list[Session]) -> dict[str, list[Session]]:
    """Group sessions by relative time periods"""
    groups: dict[str, list[Session]] = {
        "今天": [],
        "昨天": [],
        "本周": [],
        "本月": [],
        "更早": [],
    }

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    for session in sessions:
        session_time = session.created_at

        if isinstance(session_time, (int, float)):
            # Assume milliseconds if large number
            if session_time > 1e10:
                session_time = datetime.fromtimestamp(session_time / 1000)
            else:
                session_time = datetime.fromtimestamp(session_time)

        if session_time >= today:
            groups["今天"].append(session)
        elif session_time >= yesterday:
            groups["昨天"].append(session)
        elif session_time >= week_ago:
            groups["本周"].append(session)
        elif session_time >= month_ago:
            groups["本月"].append(session)
        else:
            groups["更早"].append(session)

    # Remove empty groups
    return {k: v for k, v in groups.items() if v}


def display_sessions_list(
    agent: BaseAgent, sessions: list[Session], page_size: int = 20, show_pagination: bool = True
) -> None:
    """Display sessions with pagination support"""
    total = len(sessions)

    if total == 0:
        print("   (无会话)")
        return

    # Show all sessions with pagination
    current_page = 0
    total_pages = (total + page_size - 1) // page_size

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total)

        # Display current page
        for i in range(start_idx, end_idx):
            session = sessions[i]
            title = agent.get_formatted_title(session)
            uri = agent.get_session_uri(session)
            print(f"   • {title} {uri}")

        # Show pagination info
        if show_pagination and total_pages > 1:
            print(f"\n   第 {current_page + 1}/{total_pages} 页 (共 {total} 个会话)")

            if current_page < total_pages - 1:
                print("   按 Enter 查看更多，或输入 'q' 退出")
                try:
                    user_input = input("> ").strip().lower()
                    if user_input == "q":
                        break
                    current_page += 1
                    print()
                except EOFError, KeyboardInterrupt:
                    print()
                    break
            else:
                print("   已显示全部会话")
                break
        else:
            if total > page_size:
                print(f"\n   ... 还有 {total - page_size} 个会话未显示")
            break


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
    parser.add_argument("uri", nargs="?", help="Agent session URI to dump (e.g., opencode://session-id)")
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
    parser.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="Number of sessions to display per page (default: 20)",
    )
    args = parser.parse_args()

    # Handle URI mode first
    if args.uri:
        uri_result = parse_uri(args.uri)
        if uri_result is None:
            print(f"❌ 无效的 URI 格式: {args.uri}")
            print("\n支持的 URI 格式:")
            print("  - opencode://<session_id>")
            print("  - codex://<session_id>")
            print("  - kimi://<session_id>")
            print("  - claude://<session_id>")
            return 1

        scheme, session_id = uri_result

        # Scan for available agents
        scanner = AgentScanner()
        available_agents = scanner.get_available_agents()

        if not available_agents:
            print("❌ 未找到任何可用的 Agent Tools 会话。")
            return 1

        # Find the session
        result = find_session_by_id(scanner, session_id)
        if result is None:
            print(f"❌ 未找到会话: {args.uri}")
            return 1

        agent, session = result

        # Verify the URI scheme matches the agent
        expected_agent_name = VALID_URI_SCHEMES.get(scheme)
        if agent.name != expected_agent_name:
            print(f"❌ URI scheme 与会话不匹配: {args.uri}")
            print(f"   该会话属于 {agent.display_name}，但 URI 使用了 {scheme}://")
            return 1

        # Get session data and render
        try:
            session_data = agent.get_session_data(session)
            output = render_session_text(args.uri, session_data)
            print(output)
            return 0
        except Exception as e:
            print(f"❌ 获取会话数据失败: {e}")
            return 1

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
    available_agents = scanner.get_available_agents()

    if not available_agents:
        print("❌ 未找到任何可用的 Agent Tools 会话。")
        print("\n支持的 Agent Tools:")
        print("  - OpenCode: ~/.local/share/opencode/opencode.db")
        print("  - Codex: ~/.codex/sessions/{YYYY}/{MM}/{DD}/")
        print("  - Kimi: ~/.kimi/sessions/{project_id}/{session_id}/")
        print("  - Claude Code: ~/.claude/projects/{project_id}/")
        return

    # List mode
    if args.list:
        print(f"📋 列出最近 {args.days} 天的会话:\n")
        print("-" * 60)

        for agent in available_agents:
            # Get filtered sessions with days parameter
            sessions = agent.get_sessions(days=args.days)
            print(f"\n📁 {agent.display_name} ({len(sessions)} 个会话)")

            if sessions:
                display_sessions_list(agent, sessions, page_size=args.page_size)
            else:
                print(f"   (最近 {args.days} 天内无会话)")

        print("\n" + "=" * 60)
        print("提示: 使用 --interactive 进入交互式导出模式")
        print()
        return 0

    # Interactive mode
    # Select agent
    if len(available_agents) == 1:
        selected_agent = available_agents[0]
        print(f"自动选择: {selected_agent.display_name}\n")
    else:
        selected_agent = select_agent_interactive(available_agents, days=args.days)
        if not selected_agent:
            print("\n⚠️  未选择 Agent Tool，退出。")
            return 1
        print(f"\n已选择: {selected_agent.display_name}\n")

    # Get sessions for the selected agent
    sessions = selected_agent.get_sessions(days=args.days)

    if not sessions:
        print(f"⚠️  未找到最近 {args.days} 天内的会话。")
        return 1

    print(f"📊 找到 {len(sessions)} 个会话 (最近 {args.days} 天)\n")

    # Show warning if too many sessions
    if len(sessions) > 100:
        print(f"⚠️  注意: 会话数量较多 ({len(sessions)} 个)，建议使用 --days 缩小时间范围")
        print("   例如: agent-dump --interactive --days 1\n")

    # Select sessions
    selected_sessions = select_sessions_interactive(sessions, selected_agent)
    if not selected_sessions:
        print("\n⚠️  未选择会话，退出。")
        return 1

    print(f"\n✓ 选择了 {len(selected_sessions)} 个会话\n")

    # Export
    output_base_dir = Path(args.output)
    exported = export_sessions(selected_agent, selected_sessions, output_base_dir)

    print(f"\n✅ 成功导出 {len(exported)} 个会话到 {output_base_dir}/{selected_agent.name}/")
    return 0


if __name__ == "__main__":
    main()
