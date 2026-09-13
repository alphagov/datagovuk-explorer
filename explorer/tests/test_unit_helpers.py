"""Unit tests for explorer/helpers.py — date formatting and theme labels.

Pure functions, no DB or request: these lock in the offset→UTC conversion
(the reason the helper exists) and the label fallback.
"""

from explorer.helpers import format_date, theme_label


def test_format_date_renders_dd_mm_yyyy():
    assert format_date("2021-01-31T12:00:00") == "31/01/2021"


def test_format_date_converts_offsets_to_utc():
    # 23:30 at UTC-5 is the next day in UTC — the conversion must show that.
    assert format_date("2021-01-31T23:30:00-05:00") == "01/02/2021"


def test_format_date_blank_and_invalid():
    assert format_date(None) == "—"
    assert format_date("") == "—"
    assert format_date("not-a-date") == "not-a-date"


def test_theme_label_known_and_fallback():
    assert theme_label("towns-and-cities") == "Towns & Cities"
    assert theme_label("space-exploration") == "Space Exploration"
