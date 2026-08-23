"""OpenCode agent handler."""

from pathlib import Path

from agent_dump.agents.sqlite_sessions import SQLiteSessionAgent
from agent_dump.diagnostics import DiagnosticError, source_missing
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import ProviderRoots, SearchRoot


class OpenCodeAgent(SQLiteSessionAgent):
    """Handler for OpenCode sessions."""

    provider_name = "opencode"
    provider_display_name = "OpenCode"

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        roots = ProviderRoots.from_env_or_home()
        return (
            SearchRoot("XDG/LOCALAPPDATA opencode.db", roots.opencode_root / "opencode.db"),
            SearchRoot("local development fallback", Path("data/opencode/opencode.db")),
        )

    def _missing_database_error(self, db_path: Path | None) -> DiagnosticError:
        return source_missing(
            "OpenCode database is missing",
            missing_path=db_path or "opencode.db",
            searched_roots=[root.render() for root in self.get_search_roots()],
            next_steps=(
                i18n.t(Keys.DIAG_STEP_OPENCODE_DB_EXISTS),
                i18n.t(Keys.DIAG_STEP_OPENCODE_DEV_DB),
            ),
        )
