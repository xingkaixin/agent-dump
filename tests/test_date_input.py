from datetime import date

import pytest

from agent_dump.date_input import parse_date_input


@pytest.mark.parametrize("value", ["2026-04-08", "20260408", " 2026-04-08 "])
def test_parse_date_input_accepts_supported_formats(value: str) -> None:
    assert parse_date_input(value) == date(2026, 4, 8)


@pytest.mark.parametrize("value", ["", "2026/04/08", "2026-02-29", "not-a-date"])
def test_parse_date_input_rejects_invalid_values(value: str) -> None:
    assert parse_date_input(value) is None
