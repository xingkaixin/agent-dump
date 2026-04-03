"""Shared datetime helpers for session timestamps."""

from datetime import date, datetime, timezone, tzinfo


def ensure_datetime(value: datetime | int | float) -> datetime:
    """Convert supported timestamp values to datetime."""
    if isinstance(value, datetime):
        return value

    timestamp = value / 1000 if value > 1e10 else value
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def normalize_datetime_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_timestamp_utc(value: datetime | int | float) -> datetime:
    """Normalize a timestamp-like value to timezone-aware UTC."""
    return normalize_datetime_utc(ensure_datetime(value))


def get_local_timezone() -> tzinfo:
    """Return the current machine local timezone."""
    local_tz = datetime.now().astimezone().tzinfo
    return local_tz or timezone.utc


def to_local_datetime(value: datetime | int | float, local_tz: tzinfo | None = None) -> datetime:
    """Convert a timestamp to the user local timezone."""
    return normalize_timestamp_utc(value).astimezone(local_tz or get_local_timezone())


def get_local_today(local_tz: tzinfo | None = None) -> date:
    """Return today's date in the user local timezone."""
    return datetime.now(local_tz or get_local_timezone()).date()
