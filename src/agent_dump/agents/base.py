"""
Base agent handler interface
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any

from agent_dump.time_utils import to_local_datetime


@dataclass
class Session:
    """Unified session data model"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    source_path: Path
    metadata: dict[str, Any]


class BaseAgent(ABC):
    """Abstract base class for agent handlers"""

    def __init__(self, name: str, display_name: str):
        self.name = name
        self.display_name = display_name

    @abstractmethod
    def scan(self) -> list[Session]:
        """
        Scan for available sessions.
        Returns list of sessions found.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this agent tool is installed and has sessions.
        """
        pass

    @abstractmethod
    def get_sessions(self, days: int = 7) -> list[Session]:
        """
        Get sessions from the last N days.
        """
        pass

    @abstractmethod
    def export_session(self, session: Session, output_dir: Path) -> Path:
        """
        Export a single session to JSON.
        Returns the path to the exported file.
        """
        pass

    def get_formatted_title(self, session: Session) -> str:
        """Get formatted title for display"""
        title = session.title[:60] + "..." if len(session.title) > 60 else session.title
        time_str = to_local_datetime(session.created_at).strftime("%Y-%m-%d %H:%M")
        return f"{title} ({time_str})"

    def get_session_uri(self, session: Session) -> str:
        """Get the agent session URI for a session"""
        return f"{self.name}://{session.id}"

    def _build_raw_output_path(self, session: Session, output_dir: Path, suffix: str = ".raw.jsonl") -> Path:
        """Build output path for raw session export."""
        return output_dir / f"{session.id}{suffix}"

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        """Export the original session file when one exists."""
        source_path = session.source_path
        if not source_path.exists():
            raise FileNotFoundError(f"Session source not found: {source_path}")
        if not source_path.is_file():
            raise NotImplementedError(f"Raw export is not supported for session source: {source_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._build_raw_output_path(session, output_dir)
        shutil.copy2(source_path, output_path)
        return output_path

    @abstractmethod
    def get_session_data(self, session: Session) -> dict:
        """
        Get session data as a dictionary.
        Returns dict with keys: id, title, messages, etc.
        """
        pass
