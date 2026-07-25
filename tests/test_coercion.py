"""Tests for coercion.py — 不可信 provider 标量的容错转换。"""

from datetime import datetime, timezone

import pytest

from agent_dump.coercion import safe_epoch_datetime, safe_int


class TestSafeInt:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (42, 42),
            (-7, -7),
            (0, 0),
            (3.9, 3),
            ("42", 42),
            ("  42  ", 42),
            ("-7", -7),
        ],
    )
    def test_coerces_usable_values(self, value, expected):
        assert safe_int(value) == expected

    @pytest.mark.parametrize(
        "value",
        [None, "", "abc", "12abc", {}, [], object(), float("nan"), float("inf"), float("-inf")],
    )
    def test_falls_back_on_unusable_values(self, value):
        assert safe_int(value) == 0
        assert safe_int(value, default=-1) == -1

    def test_bool_is_not_treated_as_int(self):
        """True 是 int 的子类，但 token 计数里出现 bool 说明数据是坏的。"""
        assert safe_int(True) == 0
        assert safe_int(False) == 0


class TestSafeEpochDatetime:
    def test_seconds_unit(self):
        assert safe_epoch_datetime(1704067200, unit="s") == datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_milliseconds_unit(self):
        assert safe_epoch_datetime(1704067200000, unit="ms") == datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_result_is_timezone_aware_utc(self):
        result = safe_epoch_datetime(0, unit="s")
        assert result is not None and result.tzinfo == timezone.utc

    @pytest.mark.parametrize("value", [None, "1704067200", {}, [], True, False, float("nan")])
    def test_non_numeric_values_return_none(self, value):
        assert safe_epoch_datetime(value) is None

    @pytest.mark.parametrize("value", [1e18, -1e18, float("inf"), float("-inf")])
    def test_out_of_range_values_return_none_instead_of_raising(self, value):
        """裸 datetime.fromtimestamp 在这些值上抛 ValueError/OverflowError/OSError。"""
        assert safe_epoch_datetime(value, unit="s") is None

    def test_millisecond_value_read_as_seconds_is_still_bounded(self):
        assert safe_epoch_datetime(1704067200000, unit="s") is None
