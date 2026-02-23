"""
Claude Code agent handler
"""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from agent_dump.agents.base import BaseAgent, Session


class ClaudeCodeAgent(BaseAgent):
    """Handler for Claude Code sessions"""

    def __init__(self):
        super().__init__("claudecode", "Claude Code")
        self.base_path: Path | None = None
        self._sessions_index_cache: dict[str, dict] = {}

    def _find_base_path(self) -> Path | None:
        """Find the Claude Code projects directory"""
        # Priority: user data directory > local development data
        paths = [
            Path.home() / ".claude/projects",
            Path("data/claudecode"),
        ]

        for path in paths:
            if path.exists():
                return path
        return None

    def _load_sessions_index(self, project_dir: Path) -> dict[str, dict]:
        """Load sessions index for a project"""
        index_path = project_dir / "sessions-index.json"
        if not index_path.exists():
            return {}

        try:
            with open(index_path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", [])
            # Build a map of sessionId to entry data
            return {entry["sessionId"]: entry for entry in entries}
        except Exception:
            return {}

    def _get_session_metadata(self, session_id: str, project_dir: Path) -> dict | None:
        """Get session metadata from sessions-index.json"""
        cache_key = f"{project_dir.name}:{session_id}"
        if cache_key not in self._sessions_index_cache:
            # Load index for this project
            project_index = self._load_sessions_index(project_dir)
            # Update cache with all entries from this project
            for sid, entry in project_index.items():
                self._sessions_index_cache[f"{project_dir.name}:{sid}"] = entry

        return self._sessions_index_cache.get(cache_key)

    def is_available(self) -> bool:
        """Check if Claude Code sessions exist"""
        self.base_path = self._find_base_path()
        if not self.base_path:
            return False
        # Check for jsonl files in project directories
        for project_dir in self.base_path.iterdir():
            if project_dir.is_dir():
                jsonl_files = list(project_dir.glob("*.jsonl"))
                if jsonl_files:
                    return True
        return False

    def scan(self) -> list[Session]:
        """Scan for all available sessions"""
        if not self.is_available():
            return []
        return self.get_sessions(days=3650)

    def get_sessions(self, days: int = 7) -> list[Session]:
        """Get sessions from the last N days"""
        if not self.base_path:
            return []

        cutoff_time = datetime.now(UTC) - timedelta(days=days)
        sessions = []

        # Iterate through project directories
        for project_dir in self.base_path.iterdir():
            if not project_dir.is_dir():
                continue

            # Find all jsonl files (excluding index files)
            for jsonl_file in project_dir.glob("*.jsonl"):
                if jsonl_file.name == "sessions-index.json":
                    continue

                try:
                    session = self._parse_session_file(jsonl_file, project_dir)
                    if session and session.created_at >= cutoff_time:
                        sessions.append(session)
                except Exception as e:
                    print(f"警告: 解析会话文件失败 {jsonl_file}: {e}")
                    continue

        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def _parse_session_file(self, file_path: Path, project_dir: Path) -> Session | None:
        """Parse a single Claude Code session file"""
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            if not lines:
                return None

            # Extract session ID from filename
            session_id = file_path.stem

            # Parse first message to get timestamp
            first_line = json.loads(lines[0])
            timestamp_str = first_line.get("timestamp", "")

            try:
                created_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception:
                # Use file modification time
                stat = file_path.stat()
                created_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

            # Try to get title from sessions-index.json first
            metadata = self._get_session_metadata(session_id, project_dir)
            title = metadata["summary"] if metadata and metadata.get("summary") else self._extract_title(lines)

            return Session(
                id=session_id,
                title=title,
                created_at=created_at,
                updated_at=created_at,
                source_path=file_path,
                metadata={
                    "project": project_dir.name,
                    "cwd": first_line.get("cwd", ""),
                    "version": first_line.get("version", ""),
                },
            )
        except Exception:
            return None

    def get_session_uri(self, session: Session) -> str:
        """Get the agent session URI for a session - Claude uses 'claude://' scheme"""
        return f"claude://{session.id}"

    def _extract_title(self, lines: list[str]) -> str:
        """Extract title from user messages"""
        try:
            for line in lines[:20]:  # Check first 20 lines
                data = json.loads(line)
                msg = data.get("message", {})

                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if content:
                        # Handle both string and list content
                        if isinstance(content, list):
                            # Extract text from content list
                            texts = []
                            for item in content:
                                if isinstance(item, dict):
                                    texts.append(item.get("text", ""))
                                elif isinstance(item, str):
                                    texts.append(item)
                            content = " ".join(texts)
                        # Clean up and truncate
                        content = content.strip().replace("\n", " ")[:100]
                        return content
        except Exception as e:
            print(f"警告: 提取标题失败: {e}")

        return "Untitled Session"

    def get_session_data(self, session: Session) -> dict:
        """Get session data as a dictionary"""
        if not session.source_path.exists():
            raise FileNotFoundError(f"Session file not found: {session.source_path}")

        # Read all messages from the jsonl file
        messages = []
        stats = {
            "total_cost": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "message_count": 0,
        }

        with open(session.source_path, encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    msg = self._convert_to_opencode_format(data)
                    if msg:
                        messages.append(msg)
                        stats["message_count"] += 1
                except Exception as e:
                    print(f"警告: 转换消息格式失败: {e}")
                    continue

        return {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": session.metadata.get("cwd", ""),
            "version": session.metadata.get("version", ""),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": messages,
        }

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format"""
        session_data = self.get_session_data(session)

        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return output_path

    def _convert_to_opencode_format(self, data: dict) -> dict | None:
        """Convert Claude Code message format to OpenCode format"""
        msg = data.get("message", {})
        msg_type = data.get("type", "")
        timestamp_str = data.get("timestamp", "")

        try:
            timestamp = int(datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            timestamp = 0

        if msg_type == "user":
            content = msg.get("content", "")
            return {
                "id": data.get("uuid", ""),
                "role": "user",
                "agent": None,
                "mode": None,
                "model": None,
                "provider": None,
                "time_created": timestamp,
                "time_completed": None,
                "tokens": {},
                "cost": 0,
                "parts": [
                    {
                        "type": "text",
                        "text": content,
                        "time_created": timestamp,
                    }
                ],
            }

        elif msg_type == "assistant":
            content_parts = msg.get("content", [])
            parts = []

            for part in content_parts:
                part_type = part.get("type", "")
                if part_type == "text":
                    parts.append(
                        {
                            "type": "text",
                            "text": part.get("text", ""),
                            "time_created": timestamp,
                        }
                    )
                elif part_type == "tool_use":
                    parts.append(
                        {
                            "type": "tool",
                            "tool": part.get("name", ""),
                            "callID": part.get("id", ""),
                            "title": f"Tool: {part.get('name', '')}",
                            "state": {"input": part.get("input", {})},
                            "time_created": timestamp,
                        }
                    )

            return {
                "id": data.get("uuid", ""),
                "role": "assistant",
                "agent": "claude",
                "mode": None,
                "model": msg.get("model", ""),
                "provider": None,
                "time_created": timestamp,
                "time_completed": None,
                "tokens": msg.get("usage", {}),
                "cost": 0,
                "parts": parts,
            }

        elif msg_type == "tool_result":
            content = msg.get("content", [])
            text_content = ""
            if content and isinstance(content, list):
                text_content = content[0].get("text", "") if content else ""
            elif isinstance(content, str):
                text_content = content

            return {
                "id": data.get("uuid", ""),
                "role": "tool",
                "agent": None,
                "mode": None,
                "model": None,
                "provider": None,
                "time_created": timestamp,
                "time_completed": None,
                "tokens": {},
                "cost": 0,
                "parts": [
                    {
                        "type": "text",
                        "text": text_content,
                        "time_created": timestamp,
                    }
                ],
            }

        return None
