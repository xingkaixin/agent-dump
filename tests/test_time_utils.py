"""Tests for shared datetime normalization and local timezone conversion."""

from datetime import date, datetime, timedelta, timezone
import os
import subprocess
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from agent_dump.time_utils import (
    ensure_datetime,
    get_local_timezone,
    get_local_today,
    normalize_datetime_utc,
    normalize_timestamp_utc,
    to_local_datetime,
)

TOKYO = timezone(timedelta(hours=9))
CHATHAM = timezone(timedelta(hours=12, minutes=45))  # 非整小时偏移
MINUS_8 = timezone(timedelta(hours=-8))
# 有 DST 的真实时区，用于跨切换点验证
NEW_YORK = ZoneInfo("America/New_York")

EPOCH_SECONDS = 1704067200  # 2024-01-01T00:00:00Z
EPOCH_MILLIS = EPOCH_SECONDS * 1000
UTC_2024 = datetime(2024, 1, 1, tzinfo=timezone.utc)


class TestEnsureDatetime:
    def test_datetime_passes_through_unchanged(self):
        aware = datetime(2026, 5, 4, 3, 2, 1, tzinfo=TOKYO)

        assert ensure_datetime(aware) is aware

    def test_naive_datetime_passes_through_without_gaining_a_tzinfo(self):
        """ensure_datetime 不做归一化，那是 normalize_datetime_utc 的职责。"""
        naive = datetime(2026, 5, 4, 3, 2, 1)

        assert ensure_datetime(naive) is naive

    def test_seconds_are_read_as_seconds(self):
        assert ensure_datetime(EPOCH_SECONDS) == UTC_2024

    def test_milliseconds_are_read_as_milliseconds(self):
        assert ensure_datetime(EPOCH_MILLIS) == UTC_2024

    def test_float_seconds_keep_subsecond_precision(self):
        result = ensure_datetime(EPOCH_SECONDS + 0.5)

        assert result == UTC_2024 + timedelta(milliseconds=500)

    def test_result_is_always_utc_aware(self):
        for value in (EPOCH_SECONDS, EPOCH_MILLIS, float(EPOCH_SECONDS)):
            assert ensure_datetime(value).tzinfo == timezone.utc

    @pytest.mark.parametrize(
        ("value", "expected_unit"),
        [
            (1e10, "seconds"),  # 阈值本身：> 判定，等于时仍按秒
            (1e10 + 1, "millis"),
        ],
    )
    def test_unit_heuristic_threshold(self, value, expected_unit):
        """启发式阈值是 value > 1e10；这条把边界钉住，避免以后被悄悄挪动。

        1e10 秒约合公元 2286 年，1e10 毫秒约合 1970 年 4 月，两者都远离真实会话时间，
        所以阈值本身如何取舍不影响正确性——但它是隐式约定，需要有测试说明。
        """
        result = ensure_datetime(value)
        divided = value / 1000

        if expected_unit == "seconds":
            assert result == datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            assert result == datetime.fromtimestamp(divided, tz=timezone.utc)

    def test_zero_is_the_epoch_not_a_millisecond_value(self):
        assert ensure_datetime(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)


class TestNormalizeDatetimeUtc:
    def test_naive_is_assumed_to_be_utc(self):
        """provider 数据里出现 naive datetime 时的既定约定。"""
        naive = datetime(2024, 1, 1, 12, 0, 0)

        assert normalize_datetime_utc(naive) == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_aware_is_converted_not_relabelled(self):
        """+09:00 的 12:00 是 UTC 的 03:00，不是 UTC 的 12:00。"""
        aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=TOKYO)

        assert normalize_datetime_utc(aware) == datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)

    def test_fractional_offset_is_handled(self):
        aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=CHATHAM)

        assert normalize_datetime_utc(aware) == datetime(2023, 12, 31, 23, 15, 0, tzinfo=timezone.utc)

    def test_already_utc_is_unchanged(self):
        assert normalize_datetime_utc(UTC_2024) == UTC_2024

    def test_result_is_comparable_with_other_aware_datetimes(self):
        """naive 与 aware 直接比较会抛 TypeError；归一化的意义就在这里。"""
        naive = datetime(2024, 6, 1, 0, 0, 0)

        assert normalize_datetime_utc(naive) < datetime(2024, 7, 1, tzinfo=timezone.utc)


class TestNormalizeTimestampUtc:
    @pytest.mark.parametrize(
        "value",
        [EPOCH_SECONDS, EPOCH_MILLIS, float(EPOCH_SECONDS), UTC_2024, datetime(2024, 1, 1)],
    )
    def test_every_supported_input_shape_reaches_the_same_instant(self, value):
        assert normalize_timestamp_utc(value) == UTC_2024

    def test_aware_non_utc_input_is_converted(self):
        assert normalize_timestamp_utc(datetime(2024, 1, 1, 9, 0, 0, tzinfo=TOKYO)) == UTC_2024


class TestToLocalDatetime:
    def test_converts_into_the_given_zone(self):
        assert to_local_datetime(EPOCH_SECONDS, TOKYO) == datetime(2024, 1, 1, 9, 0, 0, tzinfo=TOKYO)

    def test_negative_offset(self):
        assert to_local_datetime(EPOCH_SECONDS, MINUS_8) == datetime(2023, 12, 31, 16, 0, 0, tzinfo=MINUS_8)

    def test_fractional_offset(self):
        assert to_local_datetime(EPOCH_SECONDS, CHATHAM) == datetime(2024, 1, 1, 12, 45, 0, tzinfo=CHATHAM)

    def test_accepts_naive_datetime_treating_it_as_utc(self):
        assert to_local_datetime(datetime(2024, 1, 1), TOKYO) == datetime(2024, 1, 1, 9, 0, 0, tzinfo=TOKYO)

    def test_millisecond_input(self):
        assert to_local_datetime(EPOCH_MILLIS, TOKYO) == datetime(2024, 1, 1, 9, 0, 0, tzinfo=TOKYO)

    def test_across_a_dst_transition_the_offset_differs(self):
        """同一时区在 DST 前后偏移不同；固定偏移的测试抓不到这类错误。"""
        winter = to_local_datetime(datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc), NEW_YORK)
        summer = to_local_datetime(datetime(2024, 7, 15, 12, 0, tzinfo=timezone.utc), NEW_YORK)

        assert winter.hour == 7  # EST, UTC-5
        assert summer.hour == 8  # EDT, UTC-4


class TestGetLocalTimezone:
    def test_default_timezone_preserves_dst_rules_from_environment(self):
        code = """
from datetime import datetime, timezone
from agent_dump.time_utils import get_local_timezone, to_local_datetime

local_tz = get_local_timezone()
winter = to_local_datetime(datetime(2024, 1, 15, 12, tzinfo=timezone.utc), local_tz)
summer = to_local_datetime(datetime(2024, 7, 15, 12, tzinfo=timezone.utc), local_tz)
print(winter.hour, summer.hour)
"""
        env = os.environ.copy()
        env["TZ"] = "America/New_York"

        result = subprocess.run(  # noqa: S603 - 可执行文件与脚本均由测试自身固定
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.stdout.strip() == "7 8"

    def test_falls_back_when_the_regional_timezone_is_unavailable(self, monkeypatch):
        def missing_timezone() -> ZoneInfo:
            raise ZoneInfoNotFoundError("missing")

        monkeypatch.setattr("agent_dump.time_utils.get_localzone", missing_timezone)

        assert get_local_timezone() is not None


class TestGetLocalToday:
    """collect 的默认窗口是「今天」，本地午夜边界上的 off-by-one 会静默产出空报告。"""

    @pytest.mark.parametrize(
        ("utc_now", "tz", "expected"),
        [
            # UTC 23:59 时，+09:00 已经是次日
            (datetime(2024, 3, 10, 23, 59, tzinfo=timezone.utc), TOKYO, date(2024, 3, 11)),
            # UTC 00:01 时，-08:00 还在前一日
            (datetime(2024, 3, 10, 0, 1, tzinfo=timezone.utc), MINUS_8, date(2024, 3, 9)),
            # 同一瞬间在两个偏移下分属不同日期
            (datetime(2024, 3, 10, 12, 0, tzinfo=timezone.utc), TOKYO, date(2024, 3, 10)),
            (datetime(2024, 3, 10, 12, 0, tzinfo=timezone.utc), MINUS_8, date(2024, 3, 10)),
        ],
    )
    def test_date_follows_the_local_zone(self, utc_now, tz, expected, monkeypatch):
        _freeze_now(monkeypatch, utc_now)

        assert get_local_today(tz) == expected

    @pytest.mark.parametrize("local_time", ["23:59", "00:01"])
    def test_midnight_boundaries_in_two_zones(self, local_time, monkeypatch):
        hour, minute = (int(part) for part in local_time.split(":"))
        for tz in (TOKYO, MINUS_8, CHATHAM):
            local_moment = datetime(2024, 3, 10, hour, minute, tzinfo=tz)
            _freeze_now(monkeypatch, local_moment.astimezone(timezone.utc))

            assert get_local_today(tz) == date(2024, 3, 10)

    def test_across_a_dst_transition(self, monkeypatch):
        """2024-03-10 是 America/New_York 的春季切换日。"""
        _freeze_now(monkeypatch, datetime(2024, 3, 10, 7, 30, tzinfo=timezone.utc))

        assert get_local_today(NEW_YORK) == date(2024, 3, 10)


def _freeze_now(monkeypatch, utc_moment: datetime) -> None:
    """把 datetime.now(tz) 固定到给定瞬间，保留 tz 转换行为。"""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return utc_moment.astimezone(tz) if tz is not None else utc_moment.replace(tzinfo=None)

    monkeypatch.setattr("agent_dump.time_utils.datetime", _FrozenDatetime)
