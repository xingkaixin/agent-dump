"""ZCode agent handler."""

from pathlib import Path
import sys

from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.diagnostics import DiagnosticError, source_missing
from agent_dump.paths import SearchRoot


class ZCodeAgent(OpenCodeAgent):
    """Handler for ZCode sessions."""

    def __init__(self):
        super().__init__()
        self.name = "zcode"
        self.display_name = "ZCode"

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        if sys.platform.startswith("darwin"):
            return (SearchRoot("macOS ~/.zcode db.sqlite", _zcode_db_path(Path.home())),)
        if sys.platform.startswith("win"):
            return (SearchRoot("Windows %USERPROFILE%\\.zcode db.sqlite", _zcode_db_path(Path.home())),)
        return ()

    def _missing_database_error(self, db_path: Path | None) -> DiagnosticError:
        return source_missing(
            "ZCode database is missing",
            missing_path=db_path or "~/.zcode/cli/db/db.sqlite",
            searched_roots=[root.render() for root in self.get_search_roots()],
            next_steps=(
                "确认 ZCode 已在 macOS 或 Windows 本机生成会话数据库。",
                "macOS 检查 `~/.zcode/cli/db/db.sqlite`；Windows 检查 `%USERPROFILE%\\.zcode\\cli\\db\\db.sqlite`。",
                "Linux 暂无 ZCode 默认会话路径。",
            ),
        )


def _zcode_db_path(home: Path) -> Path:
    return home / ".zcode" / "cli" / "db" / "db.sqlite"
