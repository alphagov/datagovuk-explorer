"""Unit tests for the Jinja2 backend's custom filters (explorer/jinja2.py).

Pure functions — no DB, no request. These filters render on every page, and
the formatting edge cases (em-dash fallbacks, half-up rounding, the
"< 0.1%" floor, insertion-order JSON) are not otherwise asserted. The
registration test renders through the configured engine so a dropped
``env.filters[...]`` line fails here rather than silently in a template.
"""

import json

import pytest
from django.template import engines

from explorer.jinja2 import _dump, _num, _percent, _prop, _round1

_engine = engines["jinja2"]


# --- registration ----------------------------------------------------------
@pytest.mark.parametrize("name", ["num", "percent", "round1", "prop", "date_short", "dump", "urlencode"])
def test_filters_registered(name):
    assert name in _engine.env.filters


def test_static_global_registered():
    assert "static" in _engine.env.globals


def test_render_through_engine():
    assert _engine.from_string("{{ v|num }}").render({"v": 12345}) == "12,345"
    assert _engine.from_string("{{ v|percent }}").render({"v": 21.3}) == "21.3%"


# --- num -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        ("", "—"),
        (12345, "12,345"),
        ("12345", "12,345"),
        (12345.0, "12,345"),  # whole float drops the .0
        (12345.25, "12,345.25"),  # fractional precision preserved
    ],
)
def test_num(value, expected):
    assert _num(value) == expected


def test_num_non_numeric_passthrough():
    assert _num("not-a-number") == "not-a-number"
    # float() raises TypeError (not ValueError) for non-string types
    assert _num([1, 2]) == "[1, 2]"


# --- percent ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        ("", "—"),
        (21.3, "21.3%"),
        (21.0, "21%"),  # whole result drops the .0
        (100, "100%"),
        (0, "0%"),  # exactly zero is a real zero, not "< 0.1%"
        (0.04, "< 0.1%"),  # tiny but non-zero
    ],
)
def test_percent(value, expected):
    assert _percent(value) == expected


def test_percent_rounds_half_up_not_bankers():
    # numpy-style half-up: 0.25 → 0.3; Python's round(0.25, 1) would give 0.2
    assert _percent(0.25) == "0.3%"


def test_percent_non_numeric_passthrough():
    assert _percent("not-a-number") == "not-a-number"


# --- round1 ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (50, "50"),
        (50.0, "50"),
        (33.3, "33.3"),
        (49.96, "50"),  # rounds up to a whole number
        (0.04, "0"),  # tiny values round to exactly 0 (no "< 0.1%" here)
    ],
)
def test_round1(value, expected):
    assert _round1(value) == expected


def test_round1_bad_input_is_nan():
    assert _round1("not-a-number") == "NaN"
    assert _round1(None) == "NaN"  # float(None) raises TypeError


# --- prop ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        (1, 1),
        (1.0, 1),  # whole value → int (drops the trailing .0)
        (0.5, "0.5"),
        (0, 0),
    ],
)
def test_prop(value, expected):
    assert _prop(value) == expected


def test_prop_keeps_tiny_fraction_and_passthrough():
    assert _prop(8.26e-05) == "8.26e-05"  # shortest-round-trip form
    assert _prop("not-a-number") == "not-a-number"  # returns the value itself


# --- dump ------------------------------------------------------------------
def test_dump_preserves_order_and_unicode():
    value = {"b": 1, "a": "café"}
    out = _dump(value)
    # insertion order must be preserved (Jinja2's tojson sorts keys)
    assert out == '{\n  "b": 1,\n  "a": "café"\n}'
    assert json.loads(out) == value
    assert "café" in out  # ensure_ascii=False
