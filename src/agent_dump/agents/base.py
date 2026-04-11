"""
Base agent handler interface
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any, cast

from agent_dump.diagnostics import source_missing, unsupported_capability
from agent_dump.paths import SearchRoot
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

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        """Return provider roots checked during discovery."""
        return ()

    def get_session_head(self, session: Session) -> dict[str, Any]:
        """Get lightweight discovery metadata for one session."""
        metadata = session.metadata

        cwd_or_project = metadata.get("cwd") or metadata.get("directory") or metadata.get("project")
        if not isinstance(cwd_or_project, str) or not cwd_or_project.strip():
            cwd_or_project = str(session.source_path.parent if session.source_path.is_file() else session.source_path)

        return {
            "uri": self.get_session_uri(session),
            "agent": self.display_name,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "cwd_or_project": cwd_or_project,
            "model": metadata.get("model") or metadata.get("model_provider"),
            "message_count": cast(
                int | None,
                metadata.get("message_count") if isinstance(metadata.get("message_count"), int) else None,
            ),
            "subtargets": [],
        }

    def get_session_summary_fields(self, session: Session) -> dict[str, str | int | None]:
        """Return reduced metadata fields for list/selector display."""
        cwd = session.metadata.get("cwd")
        project = session.metadata.get("project")
        directory = session.metadata.get("directory")
        model = session.metadata.get("model")
        branch = session.metadata.get("branch")
        message_count = session.metadata.get("message_count")

        location = project or cwd or directory
        return {
            "cwd_project": str(location) if isinstance(location, str) and location.strip() else None,
            "model": str(model) if isinstance(model, str) and model.strip() else None,
            "branch": str(branch) if isinstance(branch, str) and branch.strip() else None,
            "message_count": cast(int | None, message_count if isinstance(message_count, int) else None),
            "updated_at": to_local_datetime(session.updated_at).strftime("%Y-%m-%d %H:%M"),
        }

    def _build_raw_output_path(self, session: Session, output_dir: Path, suffix: str = ".raw.jsonl") -> Path:
        """Build output path for raw session export."""
        return output_dir / f"{session.id}{suffix}"

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        """Export the original session file when one exists."""
        source_path = session.source_path
        if not source_path.exists():
            raise source_missing(
                "raw session source is missing",
                missing_path=source_path,
                searched_roots=[root.render() for root in self.get_search_roots()],
                next_steps=(
                    "确认原始会话文件仍在本地。",
                    "重新运行 `agent-dump --list` 检查该会话是否仍可见。",
                ),
            )
        if not source_path.is_file():
            raise unsupported_capability(
                "raw export is not supported for this session source",
                capability_gap="session source is a directory, not a single raw file",
                details=(f"source path: {source_path}",),
                next_steps=(
                    "改用 `--format json` 或 `--format markdown`。",
                    "若需要原始文件，请检查该 provider 是否有独立 raw 文件。",
                ),
            )

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
