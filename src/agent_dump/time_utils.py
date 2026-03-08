"""Shared datetime helpers for session timestamps."""

from datetime import date, datetime, timezone, tzinfo


def normalize_datetime_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_local_timezone() -> tzinfo:
    """Return the current machine local timezone."""
    local_tz = datetime.now().astimezone().tzinfo
    return local_tz or timezone.utc


def to_local_datetime(value: datetime, local_tz: tzinfo | None = None) -> datetime:
    """Convert a timestamp to the user local timezone."""
    return normalize_datetime_utc(value).astimezone(local_tz or get_local_timezone())


def get_local_today(local_tz: tzinfo | None = None) -> date:
    """Return today's date in the user local timezone."""
    return datetime.now(local_tz or get_local_timezone()).date()
