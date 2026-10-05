"""Unit tests for scripts.build_fts._tags_from_json."""

import pytest

from scripts.build_fts import _tags_from_json


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"tags": [{"display_name": "flood"}, {"display_name": "river"}]}, "flood river"),
        ({"tags": [{"name": "flood"}]}, "flood"),
        ({"tags": [{"display_name": "flood", "name": "ignored"}]}, "flood"),
        ({"tags": [{"display_name": "", "name": "fallback"}]}, "fallback"),
        ({"tags": [{"display_name": "  lots   of   space  "}]}, "lots of space"),
        ({"tags": []}, ""),
        ({}, ""),
        ({"tags": None}, ""),
        ({"tags": [{"display_name": ""}, {"display_name": "kept"}]}, "kept"),
        ({"tags": [{}]}, ""),
    ],
)
def test_tags_from_json(raw, expected):
    assert _tags_from_json(raw) == expected
