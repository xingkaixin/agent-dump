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


def resolve_env_path(
    name: str,
    default: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve one optional environment path with a provider-owned default."""
    resolved_environ = environ if environ is not None else os.environ
    return _get_env_path(resolved_environ, name) or default


def resolve_data_home(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    is_windows: bool | None = None,
) -> Path:
    """Resolve a platform-specific data home directory."""
    resolved_home = home if home is not None else Path.home()
    resolved_environ = environ if environ is not None else os.environ
    resolved_is_windows = os.name == "nt" if is_windows is None else is_windows

    xdg_data_home = _get_env_path(resolved_environ, "XDG_DATA_HOME")
    if xdg_data_home is not None:
        return xdg_data_home

    if resolved_is_windows:
        local_app_data = _get_env_path(resolved_environ, "LOCALAPPDATA")
        if local_app_data is not None:
            return local_app_data

        app_data = _get_env_path(resolved_environ, "APPDATA")
        if app_data is not None:
            return app_data

    return resolved_home / ".local" / "share"


def first_existing_search_root(*roots: SearchRoot) -> Path | None:
    """Return the first existing root path from labeled candidates."""
    for root in roots:
        if root.path.exists():
            return root.path
    return None
