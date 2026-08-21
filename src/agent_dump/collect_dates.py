"""Date parsing and range selection for collect mode."""

from datetime import date, datetime, timedelta, tzinfo
from enum import Enum

from agent_dump.collect_models import SUPPORTED_DATE_FORMATS
from agent_dump.time_utils import get_local_today


class CollectDateErrorCode(str, Enum):
    INVALID_FORMAT = "invalid_format"
    SINCE_AFTER_UNTIL = "since_after_until"


class CollectDateError(ValueError):
    def __init__(self, code: CollectDateErrorCode, value: str | None = None) -> None:
        self.code = code
        self.value = value
        message = f"invalid date format: {value}" if code is CollectDateErrorCode.INVALID_FORMAT else code.value
        super().__init__(message)


def parse_user_date(value: str) -> date:
    """Parse a date from the formats accepted by collect mode."""
    normalized = value.strip()
    for date_format in SUPPORTED_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date()  # noqa: DTZ007
        except ValueError:
            continue
    raise CollectDateError(CollectDateErrorCode.INVALID_FORMAT, value)


def resolve_collect_date_range(
    since: str | None,
    until: str | None,
    *,
    days: int | None = None,
    today: date | None = None,
    local_tz: tzinfo | None = None,
) -> tuple[date, date]:
    """Resolve the effective inclusive collect date range."""
    effective_today = today or get_local_today(local_tz)

    if not since and not until:
        if days is not None:
            return effective_today - timedelta(days=days), effective_today
        return effective_today, effective_today

    if since and until:
        start = parse_user_date(since)
        end = parse_user_date(until)
        if start > end:
            raise CollectDateError(CollectDateErrorCode.SINCE_AFTER_UNTIL)
        return start, end

    if since:
        start = parse_user_date(since)
        end = effective_today
        if start > end:
            raise CollectDateError(CollectDateErrorCode.SINCE_AFTER_UNTIL)
        return start, end

    end = parse_user_date(until or "")
    start = date(end.year, end.month, 1)
    if start > end:
        raise CollectDateError(CollectDateErrorCode.SINCE_AFTER_UNTIL)
    return start, end
