"""Internal types for the normalized session message contract."""

from typing import Any, TypedDict


class _NormalizedMessageRequired(TypedDict):
    id: str
    role: str
    parts: list[dict[str, Any]]


class NormalizedMessage(_NormalizedMessageRequired, total=False):
    """One normalized message while it is assembled by a provider."""

    agent: str | None
    mode: str | None
    model: str | None
    provider: str | None
    time_created: int
    time_completed: int | None
    tokens: dict[str, Any]
    cost: int | float
    tool_call_id: str
    entry_id: str
    subagent_id: str
    subagent_type: str


class _NormalizedSessionDataRequired(TypedDict):
    id: str
    title: str
    messages: list[dict[str, Any]]


class NormalizedSessionData(_NormalizedSessionDataRequired, total=False):
    """Provider-neutral session payload before JSON serialization."""

    slug: str | None
    directory: str | None
    version: str | None
    time_created: int
    time_updated: int
    summary_files: Any
    stats: dict[str, Any]
    metadata: dict[str, Any]
