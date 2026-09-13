"""Unit tests for the shared view helpers in explorer/views/core.py.

Pure functions over a fake request — no DB, no client. The pagination
arithmetic and the bogus-?page/?sort/?dir handling every page relies on,
tested once here instead of per page.
"""

from django.test import RequestFactory

from explorer.views.core import PAGE_SIZE, _page_param, _sort_dir, paginate

_rf = RequestFactory()


def _req(qs: str = ""):
    return _rf.get(f"/{qs}")


def test_page_param_defaults_and_clamps():
    assert _page_param(_req()) == 1
    assert _page_param(_req("?page=3")) == 3
    for bad in ("?page=0", "?page=-5", "?page=abc", "?page="):
        assert _page_param(_req(bad)) == 1, bad


def test_paginate_clamps_out_of_range_page():
    ctx = paginate(_req("?page=99999"), total=250)
    assert ctx == {
        "page": 3,
        "total_pages": 3,
        "page_size": PAGE_SIZE,
        "offset": 200,
        "start_index": 201,
        "end_index": 250,
    }


def test_paginate_short_and_empty():
    # A partial second page.
    ctx = paginate(_req("?page=2"), total=150)
    assert (ctx["offset"], ctx["start_index"], ctx["end_index"]) == (100, 101, 150)
    # Zero rows still yields page 1 / 1 page, with an empty 1..0 range.
    ctx = paginate(_req(), total=0)
    assert (ctx["page"], ctx["total_pages"], ctx["start_index"], ctx["end_index"]) == (1, 1, 1, 0)


def test_sort_dir_whitelist_and_fallbacks():
    cols = {"name", "count"}
    assert _sort_dir(_req(), cols, "name") == ("name", "asc")
    assert _sort_dir(_req("?sort=count&dir=desc"), cols, "name") == ("count", "desc")
    # Unknown sort falls back; any dir other than "desc" becomes "asc".
    assert _sort_dir(_req("?sort=bogus&dir=sideways"), cols, "name") == ("name", "asc")
    assert _sort_dir(_req("?sort=bogus"), cols, "count", "desc") == ("count", "desc")
