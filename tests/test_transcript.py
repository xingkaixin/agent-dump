"""Tests for transcript.py —— 只读 Transcript Interface（AD-181）。

这些断言描述「一条标准化消息里有哪些 facts」。用哪些 facts 是各投影自己的策略，
在 rendering / search_index / query_filter / collect 的测试里各自验证。
"""

import pytest

from agent_dump.transcript import read_message, read_messages


class TestPartTexts:
    @pytest.mark.parametrize(
        ("part", "expected"),
        [
            ({"type": "text", "text": "  user text  "}, ("user text",)),
            ({"type": "reasoning", "text": "  model reasoning  "}, ("model reasoning",)),
            ({"type": "plan", "input": "  implementation plan  "}, ("implementation plan",)),
            ({"type": "tool", "text": "ignored tool output"}, ()),
            ({"type": "text", "text": "   "}, ()),
            ({"text": "missing type"}, ()),
        ],
    )
    def test_supported_part_types(self, part, expected):
        assert read_message({"parts": [part]}).texts == expected

    def test_part_order_is_preserved(self):
        message = {
            "parts": [
                {"type": "reasoning", "text": "first"},
                {"type": "text", "text": "second"},
                {"type": "plan", "input": "third"},
            ]
        }

        assert read_message(message).texts == ("first", "second", "third")

    @pytest.mark.parametrize("parts", [None, "not-a-list", 42, {}])
    def test_malformed_parts_yield_nothing(self, parts):
        assert read_message({"parts": parts}).texts == ()

    def test_non_dict_parts_are_skipped(self):
        message = {"parts": [{"type": "text", "text": "kept"}, "bare string", None, 7]}

        assert read_message(message).texts == ("kept",)


class TestLegacyContent:
    """pre-parts 的 content 字段有三种形态，此前在两个消费者里各归一化了一遍。"""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("legacy string", ("legacy string",)),
            ("   ", ()),
            (["one", "two"], ("one", "two")),
            ([{"text": "  from dict  "}], ("from dict",)),
            (["keep", 42, None, {"text": "also"}], ("keep", "also")),
            ([{"no_text": "x"}], ()),
            (None, ()),
            (42, ()),
        ],
    )
    def test_shapes(self, content, expected):
        assert read_message({"content": content}).legacy_texts == expected

    def test_whitespace_is_judged_but_not_stripped_for_strings(self):
        """既有行为：空白判断用 strip 后的值，产出保留原值。改了会动到导出正文。"""
        assert read_message({"content": "  padded  "}).legacy_texts == ("  padded  ",)
        assert read_message({"content": ["  padded  "]}).legacy_texts == ("  padded  ",)

    def test_dict_items_are_stripped(self):
        assert read_message({"content": [{"text": "  padded  "}]}).legacy_texts == ("padded",)

    def test_searchable_texts_combines_parts_and_legacy(self):
        message = {"parts": [{"type": "text", "text": "from part"}], "content": "from content"}

        assert read_message(message).searchable_texts == ("from part", "from content")


class TestToolCalls:
    def test_reads_identity_and_state(self):
        message = {
            "parts": [
                {
                    "type": "tool",
                    "tool": "bash",
                    "state": {"arguments": {"cmd": "ls"}, "output": "file.txt", "prompt": "  run it  "},
                }
            ]
        }

        call = read_message(message).tool_calls[0]

        assert (call.tool, call.arguments, call.output, call.prompt) == ("bash", {"cmd": "ls"}, "file.txt", "run it")
        assert call.is_subagent is False

    def test_missing_state_yields_empty_facts(self):
        call = read_message({"parts": [{"type": "tool", "tool": "bash"}]}).tool_calls[0]

        assert (call.arguments, call.output, call.prompt) == (None, None, "")

    @pytest.mark.parametrize("state", ["not-a-dict", 42, None, []])
    def test_malformed_state_does_not_raise(self, state):
        call = read_message({"parts": [{"type": "tool", "tool": "x", "state": state}]}).tool_calls[0]

        assert call.arguments is None

    def test_subagent_calls_are_identified_and_filtered(self):
        message = {
            "parts": [
                {"type": "tool", "tool": "bash", "state": {}},
                {"type": "tool", "tool": "subagent", "nickname": "  scout  ", "state": {"prompt": "go look"}},
            ]
        }

        subagents = read_message(message).subagent_calls

        assert len(subagents) == 1
        assert subagents[0].nickname == "scout"
        assert subagents[0].prompt == "go look"

    def test_non_tool_parts_are_not_tool_calls(self):
        assert read_message({"parts": [{"type": "text", "text": "hi"}]}).tool_calls == ()


class TestMessageIdentity:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [({"role": "USER"}, "user"), ({"role": "Assistant"}, "assistant"), ({}, "unknown"), ({"role": None}, "none")],
    )
    def test_role_is_normalized_to_lowercase(self, raw, expected):
        assert read_message(raw).role == expected

    def test_nickname_is_stripped(self):
        assert read_message({"nickname": "  helper  "}).nickname == "helper"
        assert read_message({}).nickname == ""

    def test_raw_message_stays_reachable(self):
        message = {"role": "user", "provider_specific": "kept"}

        assert read_message(message).raw is message


class TestReadMessages:
    def test_iterates_a_session_payload(self):
        data = {"messages": [{"role": "user"}, {"role": "assistant"}]}

        assert [m.role for m in read_messages(data)] == ["user", "assistant"]

    def test_non_dict_messages_are_skipped(self):
        data = {"messages": [{"role": "user"}, "bare", None, 42]}

        assert [m.role for m in read_messages(data)] == ["user"]

    @pytest.mark.parametrize("messages", [None, "not-a-list", {}, 42])
    def test_malformed_payload_yields_nothing(self, messages):
        assert list(read_messages({"messages": messages})) == []

    def test_missing_messages_key_yields_nothing(self):
        assert list(read_messages({})) == []
