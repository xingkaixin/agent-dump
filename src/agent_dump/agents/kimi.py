"""
Kimi agent handler
"""

from datetime import datetime, timedelta
import json
from pathlib import Path

from agent_dump.agents.base import BaseAgent, Session


class KimiAgent(BaseAgent):
    """Handler for Kimi sessions"""

    def __init__(self):
        super().__init__("kimi", "Kimi")
        self.base_path: Path | None = None

    def _find_base_path(self) -> Path | None:
        """Find the Kimi sessions directory"""
        # Priority: user data directory > local development data
        paths = [
            Path.home() / ".kimi/sessions",
            Path("data/kimi"),
        ]

        for path in paths:
            if path.exists():
                return path
        return None

    def is_available(self) -> bool:
        """Check if Kimi sessions exist"""
        self.base_path = self._find_base_path()
        if not self.base_path:
            return False
        # Check for metadata.json files
        return len(list(self.base_path.rglob("metadata.json"))) > 0

    def scan(self) -> list[Session]:
        """Scan for all available sessions"""
        if not self.is_available():
            return []
        return self.get_sessions(days=3650)

    def get_sessions(self, days: int = 7) -> list[Session]:
        """Get sessions from the last N days"""
        if not self.base_path:
            return []

        cutoff_time = datetime.now() - timedelta(days=days)
        sessions = []

        # Find all metadata.json files
        for metadata_file in self.base_path.rglob("metadata.json"):
            try:
                session = self._parse_session(metadata_file)
                if session and session.created_at >= cutoff_time:
                    sessions.append(session)
            except Exception as e:
                print(f"警告: 解析会话文件失败 {metadata_file}: {e}")
                continue

        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def _parse_session(self, metadata_path: Path) -> Session | None:
        """Parse a Kimi session from metadata file"""
        try:
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            session_dir = metadata_path.parent
            wire_path = session_dir / "wire.jsonl"

            if not wire_path.exists():
                return None

            session_id = metadata.get("session_id", "")
            title = metadata.get("title", "Untitled Session")
            created_at = datetime.fromtimestamp(metadata.get("wire_mtime", 0))

            return Session(
                id=session_id,
                title=title,
                created_at=created_at,
                updated_at=created_at,
                source_path=session_dir,
                metadata={
                    "wire_file": str(wire_path),
                    "title_generated": metadata.get("title_generated", False),
                },
            )
        except Exception:
            return None

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format"""
        wire_path = session.source_path / "wire.jsonl"

        if not wire_path.exists():
            raise FileNotFoundError(f"Wire file not found: {wire_path}")

        # Read all messages from the wire.jsonl file
        messages = []
        stats = {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "message_count": 0,
        }

        with open(wire_path, encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    msg = self._convert_to_opencode_format(data)
                    if msg:
                        messages.append(msg)
                        stats["message_count"] += 1
                        # Extract token info if available
                        token_usage = data.get("message", {}).get("usage", {})
                        if token_usage:
                            stats["total_input_tokens"] += token_usage.get("input_tokens", 0)
                            stats["total_output_tokens"] += token_usage.get("output_tokens", 0)
                except Exception as e:
                    print(f"警告: 转换消息格式失败: {e}")
                    continue

        session_data = {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": str(session.source_path),
            "version": None,
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": messages,
        }

        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return output_path

    def _convert_to_opencode_format(self, data: dict) -> dict | None:
        """Convert Kimi message format to OpenCode format"""
        msg = data.get("message", {})
        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})
        timestamp = data.get("timestamp", 0)

        if msg_type == "TurnBegin":
            user_input = payload.get("user_input", [])
            text = ""
            if user_input and isinstance(user_input, list):
                text = user_input[0].get("text", "")

            return {
                "id": str(timestamp),
                "role": "user",
                "agent": None,
                "mode": None,
                "model": None,
                "provider": None,
                "time_created": int(timestamp * 1000),
                "time_completed": None,
                "tokens": {},
                "cost": 0,
                "parts": [
                    {
                        "type": "text",
                        "text": text,
                        "time_created": int(timestamp * 1000),
                    }
                ],
            }

        elif msg_type == "ContentPart":
            part_type = payload.get("type", "")
            content = ""

            if part_type == "think":
                content = payload.get("think", "")
                part_data = {"type": "reasoning", "text": content, "time_created": int(timestamp * 1000)}
            elif part_type == "text":
                content = payload.get("text", "")
                part_data = {"type": "text", "text": content, "time_created": int(timestamp * 1000)}
            else:
                return None

            return {
                "id": str(timestamp),
                "role": "assistant",
                "agent": "kimi",
                "mode": None,
                "model": None,
                "provider": None,
                "time_created": int(timestamp * 1000),
                "time_completed": None,
                "tokens": {},
                "cost": 0,
                "parts": [part_data],
            }

        elif msg_type == "ToolCall":
            tool = payload.get("function", {})
            return {
                "id": str(timestamp),
                "role": "assistant",
                "agent": None,
                "mode": "tool",
                "model": None,
                "provider": None,
                "time_created": int(timestamp * 1000),
                "time_completed": None,
                "tokens": {},
                "cost": 0,
                "parts": [
                    {
                        "type": "tool",
                        "tool": tool.get("name", ""),
                        "callID": tool.get("id", ""),
                        "title": f"Tool: {tool.get('name', '')}",
                        "state": {"arguments": tool.get("arguments", {})},
                        "time_created": int(timestamp * 1000),
                    }
                ],
            }

        elif msg_type == "ToolResult":
            result = payload.get("return_value", {})
            return {
                "id": str(timestamp),
                "role": "tool",
                "agent": None,
                "mode": None,
                "model": None,
                "provider": None,
                "time_created": int(timestamp * 1000),
                "time_completed": None,
                "tokens": {},
                "cost": 0,
                "parts": [
                    {
                        "type": "text",
                        "text": str(result),
                        "time_created": int(timestamp * 1000),
                    }
                ],
            }

        return None
