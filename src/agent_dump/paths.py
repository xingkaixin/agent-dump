"""Internal provider path resolution helpers."""

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class SearchRoot:
    """One candidate path examined during discovery."""

    label: str
    path: Path

    def render(self) -> str:
        return f"{self.label}: {self.path}"


def _get_env_path(environ: Mapping[str, str], name: str) -> Path | None:
    """Read a non-empty path from environment variables."""
    value = environ.get(name)
    if not value:
        return None
    return Path(value)


def _get_data_home(*, home: Path, environ: Mapping[str, str], is_windows: bool) -> Path:
    """Resolve a platform-specific data home directory."""
    xdg_data_home = _get_env_path(environ, "XDG_DATA_HOME")
    if xdg_data_home is not None:
        return xdg_data_home

    if is_windows:
        local_app_data = _get_env_path(environ, "LOCALAPPDATA")
        if local_app_data is not None:
            return local_app_data

        app_data = _get_env_path(environ, "APPDATA")
        if app_data is not None:
            return app_data

    return home / ".local" / "share"


def first_existing_path(*paths: Path) -> Path | None:
    """Return the first existing path from candidates."""
    for path in paths:
        if path.exists():
            return path
    return None


def first_existing_search_root(*roots: SearchRoot) -> Path | None:
    """Return the first existing root path from labeled candidates."""
    for root in roots:
        if root.path.exists():
            return root.path
    return None


def render_search_roots(*roots: SearchRoot) -> tuple[str, ...]:
    """Render labeled search roots for diagnostics."""
    return tuple(root.render() for root in roots)


@dataclass(frozen=True)
class ProviderRoots:
    """Resolved provider root directories."""

    codex_root: Path
    claude_root: Path
    kimi_root: Path
    opencode_root: Path

    @classmethod
    def from_env_or_home(
        cls,
        *,
        home: Path | None = None,
        environ: Mapping[str, str] | None = None,
        is_windows: bool | None = None,
    ) -> "ProviderRoots":
        """Build provider roots from environment variables and platform defaults."""
        resolved_home = home if home is not None else Path.home()
        resolved_environ = environ if environ is not None else os.environ
        resolved_is_windows = os.name == "nt" if is_windows is None else is_windows

        codex_root = _get_env_path(resolved_environ, "CODEX_HOME") or resolved_home / ".codex"
        claude_root = _get_env_path(resolved_environ, "CLAUDE_CONFIG_DIR") or resolved_home / ".claude"
        kimi_root = _get_env_path(resolved_environ, "KIMI_SHARE_DIR") or resolved_home / ".kimi"
        data_home = _get_data_home(
            home=resolved_home,
            environ=resolved_environ,
            is_windows=resolved_is_windows,
        )
        opencode_root = data_home / "opencode"

        return cls(
            codex_root=codex_root,
            claude_root=claude_root,
            kimi_root=kimi_root,
            opencode_root=opencode_root,
        )
