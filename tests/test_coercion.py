"""Tests for coercion.py — 不可信 provider 标量的容错转换。"""

from datetime import datetime, timezone

import pytest

from agent_dump.coercion import safe_epoch_datetime, safe_float, safe_int


class TestSafeInt:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (42, 42),
            (10**400, 10**400),
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

    @pytest.mark.parametrize("value", [10**400, -(10**400)])
    def test_integer_too_large_for_float_returns_none(self, value):
        assert safe_epoch_datetime(value, unit="s") is None


class TestSafeFloat:
    """AD-160：cost 等浮点统计要与 safe_int 同一套不可信值语义。"""

    def test_numbers_pass_through(self):
        assert safe_float(1.5) == 1.5
        assert safe_float(3) == 3.0
        assert safe_float("2.25") == 2.25
        assert safe_float(" 2.25 ") == 2.25

    def test_bool_is_not_a_number(self):
        assert safe_float(True) == 0.0
        assert safe_float(False) == 0.0

    def test_nan_and_infinity_fall_back(self):
        assert safe_float(float("nan")) == 0.0
        assert safe_float(float("inf")) == 0.0
        assert safe_float(float("-inf")) == 0.0
        assert safe_float("nan") == 0.0
        assert safe_float("inf") == 0.0

    def test_unusable_values_fall_back(self):
        assert safe_float(None) == 0.0
        assert safe_float("abc") == 0.0
        assert safe_float({}) == 0.0
        assert safe_float([1.0]) == 0.0

    def test_explicit_default(self):
        assert safe_float(None, -1.0) == -1.0

    @pytest.mark.parametrize("value", [10**400, -(10**400), "1e1000000", "-1e1000000"])
    def test_overflowing_values_fall_back(self, value):
        assert safe_float(value) == 0.0
        assert safe_float(value, -1.0) == -1.0
