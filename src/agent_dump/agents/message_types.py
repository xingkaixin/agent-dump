"""Internal types for the normalized session message contract."""

from typing import Any, Literal, TypeAlias, TypedDict, TypeGuard

MessageRole: TypeAlias = Literal[
    "user",
    "assistant",
    "tool",
    "system",
    "developer",
    "unknown",
    "branch_summary",
    "compaction",
    "custom",
]
MESSAGE_ROLES: frozenset[MessageRole] = frozenset(
    {
        "user",
        "assistant",
        "tool",
        "system",
        "developer",
        "unknown",
        "branch_summary",
        "compaction",
        "custom",
    }
)
TextPartType: TypeAlias = Literal["text", "reasoning"]
StepPartType: TypeAlias = Literal["step-start", "step-finish"]


class TextPart(TypedDict):
    """Visible text or reasoning content."""

    type: TextPartType
    text: str
    time_created: int


class _ToolPartRequired(TypedDict):
    type: Literal["tool"]
    tool: str
    callID: str
    title: str
    state: dict[str, Any]
    time_created: int


class ToolPart(_ToolPartRequired, total=False):
    """One normalized tool invocation."""

    subagent_id: str
    nickname: str
    subagent_type: str


class PlanPart(TypedDict):
    """One proposed plan and its approval result."""

    type: Literal["plan"]
    input: Any
    output: Any
    approval_status: str
    time_created: int


class ImagePart(TypedDict):
    """One image payload."""

    type: Literal["image"]
    mime_type: str | None
    data: Any
    time_created: int


class _StepPartRequired(TypedDict):
    type: StepPartType
    time_created: int


class StepPart(_StepPartRequired, total=False):
    """OpenCode step metadata preserved in normalized output."""

    reason: Any
    tokens: Any
    cost: Any


NormalizedPart: TypeAlias = TextPart | ToolPart | PlanPart | ImagePart | StepPart


def is_text_part(part: NormalizedPart) -> TypeGuard[TextPart]:
    return part["type"] in {"text", "reasoning"}


def is_tool_part(part: NormalizedPart) -> TypeGuard[ToolPart]:
    return part["type"] == "tool"


def is_plan_part(part: NormalizedPart) -> TypeGuard[PlanPart]:
    return part["type"] == "plan"


class _NormalizedMessageRequired(TypedDict):
    id: str
    role: MessageRole
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
