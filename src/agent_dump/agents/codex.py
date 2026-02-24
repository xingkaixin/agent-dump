"""
Codex agent handler
"""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.message_filter import filter_messages_for_export


class CodexAgent(BaseAgent):
    """Handler for Codex sessions"""

    def __init__(self):
        super().__init__("codex", "Codex")
        self.base_path: Path | None = None
        self._titles_cache: dict[str, str] | None = None

    def _find_base_path(self) -> Path | None:
        """Find the Codex sessions directory"""
        # Priority: user data directory > local development data
        paths = [
            Path.home() / ".codex/sessions",
            Path("data/codex"),
        ]

        for path in paths:
            if path.exists():
                return path
        return None

    def _load_titles_cache(self) -> dict[str, str]:
        """Load session titles from global state file"""
        if self._titles_cache is not None:
            return self._titles_cache

        titles: dict[str, str] = {}
        global_state_path = Path.home() / ".codex/.codex-global-state.json"

        if global_state_path.exists():
            try:
                with open(global_state_path, encoding="utf-8") as f:
                    data = json.load(f)
                titles = data.get("thread-titles", {}).get("titles", {})
            except Exception as e:
                print(f"警告: 加载标题缓存失败: {e}")

        self._titles_cache = titles
        return titles

    def _get_session_title(self, session_id: str) -> str | None:
        """Get session title from global state by session ID"""
        titles = self._load_titles_cache()
        return titles.get(session_id)

    def is_available(self) -> bool:
        """Check if Codex sessions exist"""
        self.base_path = self._find_base_path()
        if not self.base_path:
            return False
        # Check if there are any jsonl files
        return len(list(self.base_path.rglob("*.jsonl"))) > 0

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

        for jsonl_file in self.base_path.rglob("*.jsonl"):
            try:
                session = self._parse_session_file(jsonl_file)
                if session and session.created_at >= cutoff_time:
                    sessions.append(session)
            except Exception as e:
                print(f"警告: 解析会话文件失败 {jsonl_file}: {e}")
                continue

        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def _extract_session_id_from_filename(self, file_path: Path) -> str:
        """Extract session ID from Codex filename

        Filename format: rollout-{timestamp}-{sessionId}.jsonl
        Example: rollout-2026-02-03T10-04-47-019c213e-c251-73a3-af66-0ec9d7cb9e29.jsonl
        """
        stem = file_path.stem  # rollout-2026-02-03T10-04-47-019c213e-c251-73a3-af66-0ec9d7cb9e29
        parts = stem.split("-")

        # Session ID is the last 5 parts (UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
        if len(parts) >= 5:
            # Last 5 parts form the UUID
            session_id = "-".join(parts[-5:])
            return session_id

        return stem

    def _parse_session_file(self, file_path: Path) -> Session | None:
        """Parse a single Codex session file"""
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            if not lines:
                return None

            # Parse first line to get session metadata
            first_line = json.loads(lines[0])
            payload = first_line.get("payload", {})

            session_id = payload.get("id", "")
            timestamp_str = payload.get("timestamp", "")

            if not session_id:
                # Extract from filename
                session_id = self._extract_session_id_from_filename(file_path)

            # Parse timestamp
            try:
                created_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception:
                # Try to get from file modification time
                stat = file_path.stat()
                created_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

            # Try to get title from global state first, then fall back to extracting from messages
            title = self._get_session_title(session_id)
            if not title:
                title = self._extract_title(lines)

            return Session(
                id=session_id,
                title=title,
                created_at=created_at,
                updated_at=created_at,
                source_path=file_path,
                metadata={
                    "cwd": payload.get("cwd", ""),
                    "cli_version": payload.get("cli_version", ""),
                    "model_provider": payload.get("model_provider", ""),
                },
            )
        except Exception:
            return None

    def _extract_title(self, lines: list[str]) -> str:
        """Extract title from session messages"""
        try:
            for line in lines[:10]:  # Check first 10 lines
                data = json.loads(line)
                payload = data.get("payload", {})

                # Look for user message
                if payload.get("type") == "message" and payload.get("role") == "user":
                    content = payload.get("content", [])
                    if content and isinstance(content, list):
                        text = content[0].get("text", "")
                        # Clean up the text
                        text = text.strip().replace("\n", " ")[:100]
                        return text
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
                        # Try to extract token info from turn_context
                        if "token_count" in str(data):
                            info = data.get("payload", {}).get("info", {})
                            if info:
                                token_usage = info.get("total_token_usage", {})
                                stats["total_input_tokens"] += token_usage.get("input_tokens", 0)
                                stats["total_output_tokens"] += token_usage.get("output_tokens", 0)
                except Exception as e:
                    print(f"警告: 转换消息格式失败: {e}")
                    continue

        return {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": session.metadata.get("cwd", ""),
            "version": session.metadata.get("cli_version", ""),
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": stats,
            "messages": messages,
        }

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single session to unified JSON format"""
        session_data = self.get_session_data(session)
        messages = session_data.get("messages")
        if isinstance(messages, list):
            session_data["messages"] = filter_messages_for_export(messages)

        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return output_path

    def _convert_to_opencode_format(self, data: dict) -> dict | None:
        """Convert Codex message format to OpenCode format"""
        msg_type = data.get("type", "")
        payload = data.get("payload", {})

        if msg_type == "session_meta":
            return None

        if msg_type == "response_item":
            item = payload.get("type", "")
            if item == "message":
                role = payload.get("role", "unknown")
                content = payload.get("content", [])

                # Build parts from content
                parts = []
                for item_content in content:
                    if item_content.get("type") == "input_text":
                        parts.append(
                            {
                                "type": "text",
                                "text": item_content.get("text", ""),
                                "time_created": 0,
                            }
                        )

                return {
                    "id": data.get("timestamp", ""),
                    "role": role,
                    "agent": None,
                    "mode": None,
                    "model": None,
                    "provider": None,
                    "time_created": 0,
                    "time_completed": None,
                    "tokens": {},
                    "cost": 0,
                    "parts": parts,
                }

            elif item == "function_call":
                return {
                    "id": data.get("timestamp", ""),
                    "role": "assistant",
                    "agent": None,
                    "mode": "tool",
                    "model": None,
                    "provider": None,
                    "time_created": 0,
                    "time_completed": None,
                    "tokens": {},
                    "cost": 0,
                    "parts": [
                        {
                            "type": "tool",
                            "tool": payload.get("name", ""),
                            "callID": payload.get("call_id", ""),
                            "title": f"Tool: {payload.get('name', '')}",
                            "state": {"arguments": payload.get("arguments", {})},
                            "time_created": 0,
                        }
                    ],
                }

        elif msg_type == "event_msg":
            event_type = payload.get("type", "")
            if event_type in ("agent_message", "agent_reasoning"):
                return {
                    "id": data.get("timestamp", ""),
                    "role": "assistant",
                    "agent": "codex",
                    "mode": None,
                    "model": None,
                    "provider": None,
                    "time_created": 0,
                    "time_completed": None,
                    "tokens": {},
                    "cost": 0,
                    "parts": [
                        {
                            "type": "text",
                            "text": payload.get("message", ""),
                            "time_created": 0,
                        }
                    ],
                }

        return None
