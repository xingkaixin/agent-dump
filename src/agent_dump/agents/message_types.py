"""Internal types for the normalized session message contract."""

from typing import Any, TypedDict


class _NormalizedPartRequired(TypedDict):
    type: str


class NormalizedPart(_NormalizedPartRequired, total=False):
    """One provider-neutral message part."""

    text: str
    tool: str
    callID: str
    title: str
    state: dict[str, Any]
    time_created: int
    mime_type: str | None
    data: Any
    input: Any
    output: Any
    approval_status: str
    subagent_id: str
    nickname: str
    subagent_type: str
    reason: Any
    tokens: Any
    cost: Any


class _NormalizedMessageRequired(TypedDict):
    id: str
    role: str
    parts: list[NormalizedPart]


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
    nickname: str
    entry_type: Any
    parent_id: str | None


class _NormalizedSessionStatsRequired(TypedDict):
    total_cost: int | float
    total_input_tokens: int
    total_output_tokens: int
    message_count: int


class NormalizedSessionStats(_NormalizedSessionStatsRequired, total=False):
    """Cross-provider totals plus optional provider-specific context facts."""

    total_tokens: int
    context_tokens_used: Any
    context_token_limit: Any
    context_usage_percent: Any


class _NormalizedSessionDataRequired(TypedDict):
    id: str
    title: str
    messages: list[NormalizedMessage]
    stats: NormalizedSessionStats


class NormalizedSessionData(_NormalizedSessionDataRequired, total=False):
    """Provider-neutral session payload before JSON serialization."""

    slug: str | None
    directory: str | None
    version: str | None
    time_created: int
    time_updated: int
    summary_files: Any
    metadata: dict[str, Any]
    summary: str
