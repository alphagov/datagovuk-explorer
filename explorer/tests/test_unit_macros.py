"""Unit tests for the shared Jinja2 macros in explorer/templates/macros/.

Each macro is rendered directly through the configured Jinja2 engine — no DB,
no client. These are the per-page "chrome" assertions (pager links, sub-nav,
facet search box / More toggle, badges, pills), done once here instead of on
every page.
"""

from django.template import engines

_engine = engines["jinja2"]


def _render(source: str, context: dict | None = None) -> str:
    return _engine.from_string(source).render(context or {})


def _macro(name: str, import_path: str) -> str:
    return f"{{% from '{import_path}' import {name} %}}"


def _pagination(**kwargs) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    return _render(_macro("pagination", "macros/_pagination.html") + f"{{{{ pagination({args}) }}}}")


def _sort_link(**kwargs) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    return _render(_macro("sort_link", "macros/_sort_link.html") + f"{{{{ sort_link({args}) }}}}")


def _facet_group(group: dict, *, search: bool = False) -> str:
    return _render(
        "{% from 'macros/_facet_group.html' import facet_group with context %}"
        f"{{{{ facet_group('{group['key']}', search={str(search).lower()}) }}}}",
        {"facet_groups": {group["key"]: group}, "facet_url": lambda k, v: f"?{k}={v}"},
    )


def _base_group(**overrides) -> dict:
    group = {
        "key": "publisher",
        "label": "Publisher",
        "aria_label": "Filter by publisher",
        "items": [{"value": "a", "name": "A", "count": 3, "href": None, "active": False}],
    }
    group.update(overrides)
    return group


# --- pagination ------------------------------------------------------------
def test_pagination_links_carry_base_and_never_undefined():
    html = _pagination(
        start=1,
        end=100,
        total=250,
        page=2,
        total_pages=3,
        base="?sort=name&dir=asc",
        label="publishers",
    )
    assert 'class="page-link"' in html
    assert "undefined" not in html
    assert "?sort=name&amp;dir=asc&amp;page=1" in html
    assert "?sort=name&amp;dir=asc&amp;page=3" in html


def test_pagination_count_and_singular_label():
    one = _pagination(start=1, end=1, total=1, page=1, total_pages=1, label="datasets", label_singular="dataset")
    assert "1 dataset" in " ".join(one.split())
    assert "pagination" not in one  # single page → no pager
    many = _pagination(start=1, end=100, total=1234, page=1, total_pages=13, label="datasets")
    assert "1,234 datasets" in " ".join(many.split())


def test_pagination_jump_form_rebuilds_query_params():
    class _GET:
        def lists(self):
            return [("sort", ["name"]), ("dir", ["asc"]), ("page", ["9"])]

    class _Request:
        GET = _GET()

    html = _render(
        "{% from 'macros/_pagination.html' import pagination with context %}"
        "{{ pagination(start=101, end=200, total=250, page=2, total_pages=3,"
        " base='?sort=name&dir=asc', label='datasets') }}",
        {"request": _Request()},
    )
    # other params are re-sent; the page is rebuilt from the current page
    assert 'name="sort" value="name"' in html
    assert 'name="dir" value="asc"' in html
    assert 'value="9"' not in html
    assert 'name="page" value="2"' in html
    assert 'min="1" max="3"' in html
    assert 'aria-label="Page number, of 3"' in html
    assert "of 3" in " ".join(html.split())


# --- sub-nav ---------------------------------------------------------------
def test_subnav_active_heading_and_sibling_links():
    html = _render(
        _macro("subnav", "macros/_subnav.html") + "{{ subnav(tabs, 'errors') }}",
        {
            "tabs": [
                {"key": "links", "label": "Links", "url": "/links"},
                {"key": "errors", "label": "Errors", "url": "/links/errors"},
            ],
        },
    )
    assert '<h1 class="nav-link nav-link--active" aria-current="page">Errors</h1>' in html
    assert '<a href="/links" class="nav-link">Links</a>' in html
    # the active report is a heading, not a self-link
    assert 'href="/links/errors"' not in html


# --- sort link -------------------------------------------------------------
def test_sort_link_toggles_direction_on_active_column():
    desc = _sort_link(key="name", label="Publisher", sort="name", dir="desc")
    assert 'class="sort-link active"' in desc
    assert "?sort=name&dir=asc" in desc  # desc is active → next click is asc
    assert 'class="sort-indicator sort-indicator--desc" aria-hidden="true"' in desc
    assert "sorted descending" in desc

    asc = _sort_link(key="name", label="Publisher", sort="name", dir="asc")
    assert "?sort=name&dir=desc" in asc
    assert "sort-indicator--asc" in asc
    assert "sorted ascending" in asc


def test_sort_link_inactive_column_is_plain_descending_arrow():
    html = _sort_link(key="views", label="Views", sort="name", dir="desc")
    assert 'class="sort-link"' in html
    assert "sort-indicator" not in html  # no chevron on the non-active column
    assert "?sort=views&dir=asc" in html


# --- facet group -----------------------------------------------------------
def test_facet_group_search_box_is_opt_in():
    html = _facet_group(_base_group(search="Search publishers"))
    assert 'class="facet-search-input"' in html
    assert 'aria-label="Search publishers"' in html
    assert 'class="facet-search-icon" aria-hidden="true"' in html
    assert 'class="facet-search-live" role="status"' in html
    assert "No results matched your search" in html

    plain = _facet_group(_base_group())
    assert "facet-search-input" not in plain


def test_facet_group_more_toggle_labels():
    collapsed = _facet_group(
        _base_group(
            list_id="publisher-facet-list",
            expanded=False,
            more={
                "href": "?publishers=all",
                "expanded": False,
                "count": 2,
                "label": "publishers",
                "param": "publishers",
            },
        ),
    )
    assert "More publishers (2)" in collapsed
    assert 'href="?publishers=all"' in collapsed
    expanded = _facet_group(
        _base_group(
            list_id="publisher-facet-list",
            expanded=True,
            more={
                "href": "?",
                "expanded": True,
                "count": 2,
                "label": "publishers",
                "param": "publishers",
            },
        ),
    )
    assert "Fewer publishers" in expanded


# --- harvest badges --------------------------------------------------------
def test_harvested_badge_states():
    src = _macro("harvested_badge, harvested_state_badge", "macros/_harvested_badge.html")
    assert 'class="badge badge-harvested"' in _render(src + "{{ harvested_badge(ds) }}", {"ds": {"harvested": 1}})
    assert 'title="Source: Src"' in _render(
        src + "{{ harvested_badge(ds) }}",
        {"ds": {"harvested": 1, "harvest_source_title": "Src"}},
    )
    assert 'class="badge badge-manual"' in _render(src + "{{ harvested_badge(ds) }}", {"ds": {"harvested": 0}})
    assert 'class="badge badge-harvested"' in _render(
        src + "{{ harvested_state_badge(ds) }}",
        {"ds": {"harvest_state": "harvested"}},
    )
    assert 'class="badge badge-manual"' in _render(
        src + "{{ harvested_state_badge(ds) }}",
        {"ds": {"harvest_state": "manual"}},
    )
    assert 'class="badge badge-unknown"' in _render(
        src + "{{ harvested_state_badge(ds) }}",
        {"ds": {"harvest_state": "unknown"}},
    )


# --- filter pills ----------------------------------------------------------
def test_filter_pills_render_and_skip_none():
    src = _macro("filter_pills", "macros/_filter_pills.html")
    html = _render(
        src + "{{ filter_pills(pills) }}",
        {
            "pills": [
                None,
                {"label": "Publisher", "value": "ONS", "href": "?", "aria": "Remove publisher filter: ONS"},
            ],
        },
    )
    assert 'class="filter-pill"' in html
    assert "ONS" in html
    assert 'aria-label="Remove publisher filter: ONS"' in html
    # an all-None list renders no pills row
    assert "filter-pill" not in _render(src + "{{ filter_pills(pills) }}", {"pills": [None]})
