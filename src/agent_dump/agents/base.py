"""
Base agent handler interface
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


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
        time_str = session.created_at.strftime("%Y-%m-%d %H:%M")
        return f"{title} ({time_str})"

    def get_session_uri(self, session: Session) -> str:
        """Get the agent session URI for a session"""
        return f"{self.name}://{session.id}"
