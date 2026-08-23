"""Shared parsing policy for user-supplied calendar dates."""

from datetime import date, datetime

_DATE_INPUT_FORMATS = ("%Y-%m-%d", "%Y%m%d")


def parse_date_input(value: str) -> date | None:
    """Parse an accepted date value, returning None when it is invalid."""
    normalized = value.strip()
    for date_format in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None
