"""Read-only view over normalized session messages.

七个 Provider 已经通过各自的 Adapter 产出形状相近的 message dict，但「这个 dict
里有什么」的解释此前散在四个下游：rendering 读 role/parts/subagent，search_index
和 query_filter 各自把 legacy `content` 的三种形态（str、list[str]、list[dict]）
归一化一遍——两处是逐字相同的代码，collect 又维护一套自己的读法。加一种 part 或
修正 legacy content 时，四个调用方可能各漂各的。

这里只回答「这条消息里有哪些 facts」；「要用哪些 facts」仍然是各投影自己的产品
策略：Markdown 渲染 subagent 提示、搜索索引连工具参数一起收、collect 排除工具事件，
这些差异是真实的，不该被合并成一个万能 renderer。

Provider 私有 schema 不进这里——它们仍然只在对应 Agent 内被解释。
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

# text 与 reasoning 都以 text 字段承载正文；plan 的正文在 input 里
_TEXT_PART_TYPES = frozenset({"text", "reasoning"})
_SUBAGENT_TOOL = "subagent"


@dataclass(frozen=True)
class ToolCall:
    """One tool part's identity and state, without deciding what to do with it."""

    tool: str
    arguments: Any
    output: Any
    prompt: str
    nickname: str

    @property
    def is_subagent(self) -> bool:
        return self.tool == _SUBAGENT_TOOL


@dataclass(frozen=True)
class TranscriptMessage:
    """One normalized message's facts."""

    role: str
    nickname: str
    texts: tuple[str, ...]
    legacy_texts: tuple[str, ...]
    tool_calls: tuple[ToolCall, ...]
    raw: dict[str, Any]

    @property
    def subagent_calls(self) -> tuple[ToolCall, ...]:
        return tuple(call for call in self.tool_calls if call.is_subagent)

    @property
    def searchable_texts(self) -> tuple[str, ...]:
        """Part text plus the legacy `content` field some providers still write."""
        return self.texts + self.legacy_texts


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _part_texts(parts: Any) -> tuple[str, ...]:
    if not isinstance(parts, list):
        return ()
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type in _TEXT_PART_TYPES:
            text = _clean(part.get("text"))
        elif part_type == "plan":
            text = _clean(part.get("input"))
        else:
            continue
        if text:
            texts.append(text)
    return tuple(texts)


def _legacy_content_texts(content: Any) -> tuple[str, ...]:
    """Normalize the pre-parts `content` field: a string, or a list of strings/dicts.

    Provider 会话里仍有这三种形态并存；把归一化放在这里，是因为它此前在
    search_index 与 query_filter 各写了一遍逐字相同的代码。
    """
    # 空白判断用 strip 后的值，产出保留原值：str 与 list[str] 分支此前就是这样，
    # 而 dict 分支产出的是 strip 后的值。这个不对称是既有行为，改了会动到导出正文。
    if isinstance(content, str):
        return (content,) if content.strip() else ()
    if not isinstance(content, list):
        return ()

    texts: list[str] = []
    for item in content:
        if isinstance(item, str):
            if item.strip():
                texts.append(item)
        elif isinstance(item, dict):
            text = _clean(item.get("text"))
            if text:
                texts.append(text)
    return tuple(texts)


def _tool_calls(parts: Any) -> tuple[ToolCall, ...]:
    if not isinstance(parts, list):
        return ()
    calls: list[ToolCall] = []
    for part in parts:
        if not isinstance(part, dict) or part.get("type") != "tool":
            continue
        state = part.get("state")
        state = state if isinstance(state, dict) else {}
        calls.append(
            ToolCall(
                tool=str(part.get("tool") or ""),
                arguments=state.get("arguments"),
                output=state.get("output"),
                prompt=_clean(state.get("prompt")),
                nickname=_clean(part.get("nickname")),
            )
        )
    return tuple(calls)


def read_message(message: dict[str, Any]) -> TranscriptMessage:
    """Read one normalized message's facts."""
    parts = message.get("parts")
    return TranscriptMessage(
        role=str(message.get("role", "unknown")).lower(),
        nickname=_clean(message.get("nickname")),
        texts=_part_texts(parts),
        legacy_texts=_legacy_content_texts(message.get("content")),
        tool_calls=_tool_calls(parts),
        raw=message,
    )


def read_messages(session_data: Mapping[str, Any]) -> Iterator[TranscriptMessage]:
    """Iterate a session payload's messages, skipping anything that is not one."""
    messages = session_data.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if isinstance(message, dict):
            yield read_message(message)
