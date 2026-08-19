"""Date parsing and range selection for collect mode."""

from datetime import date, datetime, timedelta, tzinfo

from agent_dump.collect_models import SUPPORTED_DATE_FORMATS
from agent_dump.time_utils import get_local_today


def parse_user_date(value: str) -> date:
    """Parse a date from the formats accepted by collect mode."""
    normalized = value.strip()
    for date_format in SUPPORTED_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date()  # noqa: DTZ007
        except ValueError:
            continue
    raise ValueError(f"invalid date format: {value}")


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
            raise ValueError("since_after_until")
        return start, end

    if since:
        start = parse_user_date(since)
        end = effective_today
        if start > end:
            raise ValueError("since_after_until")
        return start, end

    end = parse_user_date(until or "")
    start = date(end.year, end.month, 1)
    if start > end:
        raise ValueError("since_after_until")
    return start, end
