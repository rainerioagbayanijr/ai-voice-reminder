from datetime import date

import pytest

from app.services.dates import display_english_date, spoken_english_date


@pytest.mark.parametrize(
    "value,expected",
    [
        (date(2026, 11, 15), "November fifteenth, two thousand twenty-six"),
        (date(2026, 1, 1), "January first, two thousand twenty-six"),
        (date(2028, 2, 29), "February twenty-ninth, two thousand twenty-eight"),
        (date(2030, 12, 31), "December thirty-first, two thousand thirty"),
        (date(2000, 3, 2), "March second, two thousand"),
        (date(9999, 6, 3), "June third, nine thousand nine hundred ninety-nine"),
    ],
)
def test_spoken_dates_use_only_english_words(value, expected):
    result = spoken_english_date(value)
    assert result == expected
    assert not any(char.isdigit() for char in result)


def test_display_date_remains_readable_for_email():
    assert display_english_date(date(2026, 11, 15)) == "November 15, 2026"
