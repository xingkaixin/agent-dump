"""Coercion helpers for untrusted scalar values read from provider stores.

Session stores are written by other tools, so any field can be NULL, a string,
or out of range. An unguarded `int()` or `value / 1000` on such a field raises
mid-scan and — before provider isolation degrades it — takes the surrounding
command down with it. These helpers give the field a sane default instead.
"""

from datetime import datetime, timezone
import math
from typing import Any

# datetime.fromtimestamp 在超出平台可表示范围时抛 ValueError/OverflowError/OSError，
# 各平台阈值不同；用一个远超任何真实会话时间的常量统一挡掉
_MAX_EPOCH_SECONDS = 32503680000.0  # 3000-01-01Z


def safe_int(value: Any, default: int = 0) -> int:
    """Coerce a provider value to int, falling back to default."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return default if value != value or value in (float("inf"), float("-inf")) else int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a provider value to float, falling back to default.

    与 safe_int 同一套语义：bool 不是数值（True 会静默变成 1.0），NaN/Inf 不可累加
    ——一次相加就能把整份统计变成 nan。
    """
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            number = float(value.strip())
        else:
            return default
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return number


def safe_epoch_datetime(value: Any, *, unit: str = "s") -> datetime | None:
    """Convert an epoch value to an aware UTC datetime, or None when unusable.

    `unit` 由调用方按 provider 的实际存储格式显式声明，不做启发式猜测。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(seconds):
        return None
    if unit == "ms":
        seconds /= 1000.0
    if abs(seconds) > _MAX_EPOCH_SECONDS:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
