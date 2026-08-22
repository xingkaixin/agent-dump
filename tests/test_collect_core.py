"""Collect date, event, chunk, and summary normalization tests."""

from datetime import date, timedelta, timezone

import pytest

from agent_dump.collect import (
    CollectEvent,
    chunk_collect_events,
    extract_collect_events,
    resolve_collect_date_range,
)
from agent_dump.collect_dates import CollectDateError, CollectDateErrorCode, parse_user_date
from agent_dump.collect_summary import (
    empty_summary_payload,
    merge_summary_payloads,
    normalize_summary_payload,
)


class TestCollectDates:
    def test_both_missing_defaults_today(self):
        today = date(2026, 3, 5)
        since, until = resolve_collect_date_range(None, None, today=today)
        assert since == today
        assert until == today

    def test_days_defaults_to_relative_window(self) -> None:
        since, until = resolve_collect_date_range(None, None, days=7, today=date(2026, 3, 5))
        assert since == date(2026, 2, 26)
        assert until == date(2026, 3, 5)

    @pytest.mark.parametrize(
        ("since_value", "until_value", "expected_since", "expected_until"),
        [
            ("2026-03-01", "2026-03-03", date(2026, 3, 1), date(2026, 3, 3)),
            ("2026-03-01", None, date(2026, 3, 1), date(2026, 3, 5)),
            (None, "20260210", date(2026, 2, 1), date(2026, 2, 10)),
        ],
    )
    def test_explicit_date_options_override_days(
        self,
        since_value: str | None,
        until_value: str | None,
        expected_since: date,
        expected_until: date,
    ) -> None:
        since, until = resolve_collect_date_range(
            since_value,
            until_value,
            days=30,
            today=date(2026, 3, 5),
        )
        assert since == expected_since
        assert until == expected_until

    def test_since_only_defaults_until_today(self):
        today = date(2026, 3, 5)
        since, until = resolve_collect_date_range("2026-03-01", None, today=today)
        assert since == date(2026, 3, 1)
        assert until == today

    def test_until_only_defaults_since_month_start(self):
        since, until = resolve_collect_date_range(None, "20260210", today=date(2026, 3, 5))
        assert since == date(2026, 2, 1)
        assert until == date(2026, 2, 10)

    def test_invalid_range(self):
        with pytest.raises(CollectDateError) as error:
            resolve_collect_date_range("2026-03-05", "2026-03-01")

        assert error.value.code is CollectDateErrorCode.SINCE_AFTER_UNTIL

    def test_invalid_format(self):
        with pytest.raises(CollectDateError) as error:
            parse_user_date("not-a-date")

        assert error.value.code is CollectDateErrorCode.INVALID_FORMAT
        assert error.value.value == "not-a-date"
        assert str(error.value) == "invalid date format: not-a-date"

    def test_defaults_today_in_local_timezone(self):
        local_tz = timezone(timedelta(hours=8))
        since, until = resolve_collect_date_range(None, None, local_tz=local_tz, today=None)
        assert since == until


class TestCollectExtraction:
    def test_extract_collect_events_keeps_high_signal_structures(self):
        session_data = {
            "messages": [
                {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "你好"},
                        {"type": "text", "text": "请修复 /repo/app.py 里的报错"},
                    ],
                },
                {
                    "role": "assistant",
                    "parts": [
                        {"type": "text", "text": "我决定先检查 app.py。"},
                        {"type": "tool", "tool": "read_file", "state": {"path": "/repo/app.py"}},
                        {"type": "text", "text": "```py\nprint('x')\n```"},
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "parts": [{"type": "text", "text": "Traceback: FileNotFoundError in /repo/app.py"}],
                },
            ]
        }

        events, truncated = extract_collect_events(session_data)

        assert truncated is False
        assert [event.kind for event in events] == [
            "user_intent",
            "decision",
            "code",
        ]
        assert events[0].files == ("/repo/app.py",)

    def test_extract_collect_events_ignores_tool_only_sessions(self):
        session_data = {
            "messages": [
                {
                    "role": "assistant",
                    "parts": [
                        {
                            "type": "tool",
                            "tool": "exec_command",
                            "state": {
                                "arguments": {"cmd": "sed -n '1,80p' app.py"},
                                "output": [
                                    {
                                        "type": "text",
                                        "text": "Wall time: 0.1 seconds\nOutput:\n" + "x" * 1000,
                                    }
                                ],
                            },
                        }
                    ],
                }
            ]
        }

        events, truncated = extract_collect_events(session_data, fallback_text_fn=lambda: "fallback text")

        assert truncated is False
        assert len(events) == 1
        assert events[0].kind == "fallback"
        assert events[0].text == "fallback text"

    def test_extract_collect_events_ignores_tool_messages_and_parts(self):
        session_data = {
            "messages": [
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "请修复 /repo/app.py 的失败"}],
                },
                {
                    "role": "assistant",
                    "parts": [
                        {"type": "text", "text": "我会先定位相关代码。"},
                        {
                            "type": "tool",
                            "tool": "exec_command",
                            "state": {
                                "arguments": {"cmd": "pytest"},
                                "output": "FAILED tests/test_app.py",
                            },
                        },
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "parts": [{"type": "text", "text": "Traceback: FileNotFoundError in /repo/app.py"}],
                },
            ]
        }

        events, truncated = extract_collect_events(session_data)

        assert truncated is False
        assert [event.role for event in events] == ["user", "assistant"]
        assert [event.kind for event in events] == ["user_intent", "assistant_key"]
        assert "exec_command" not in "\n".join(event.text for event in events)
        assert "Traceback" not in "\n".join(event.text for event in events)

    def test_extract_collect_events_falls_back_when_empty(self):
        events, truncated = extract_collect_events({"messages": []}, fallback_text_fn=lambda: "fallback text")

        assert truncated is False
        assert len(events) == 1
        assert events[0].kind == "fallback"
        assert events[0].text == "fallback text"

    def test_extract_collect_events_respects_char_budget(self):
        session_data = {
            "messages": [
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "x" * 120}],
                },
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "text": "y" * 120}],
                },
            ]
        }

        events, truncated = extract_collect_events(session_data, char_budget=130)

        assert truncated is True
        assert len(events) == 1

    def test_chunk_collect_events_splits_long_event_sequences(self):
        events = [
            CollectEvent(kind="user_intent", role="user", text="a" * 1200),
            CollectEvent(kind="assistant_key", role="assistant", text="b" * 1200),
            CollectEvent(kind="decision", role="assistant", text="c" * 1200),
        ]

        chunks = chunk_collect_events(events, target_chars=1500)

        assert len(chunks) == 3
        assert all(chunks)

    def test_normalize_summary_payload_filters_unknown_and_dedupes(self):
        payload = normalize_summary_payload(
            {
                "topics": ["修复 collect", "修复 collect", ""],
                "errors": "timeout",
                "unknown": ["x"],
            }
        )

        assert payload["topics"] == ["修复 collect"]
        assert payload["errors"] == ["timeout"]
        assert set(payload) == {
            "topics",
            "decisions",
            "key_actions",
            "code_changes",
            "errors",
            "tools_used",
            "files",
            "artifacts",
            "open_questions",
            "notes",
        }

    def test_merge_summary_payloads_dedupes_per_field(self):
        merged = merge_summary_payloads(
            [
                {**empty_summary_payload(), "topics": ["A"], "errors": ["E1"]},
                {**empty_summary_payload(), "topics": ["A", "B"], "errors": ["E2"]},
            ]
        )

        assert merged["topics"] == ["A", "B"]
        assert merged["errors"] == ["E1", "E2"]
