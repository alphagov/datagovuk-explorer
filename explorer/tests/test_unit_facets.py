"""Unit tests for the shared facet logic — the facet-group builders in
explorer/facets.py and the report statement builder's facet substitution
in explorer/queries/reports.py.

Pure functions over hand-built dicts — no DB, no Django, no client fixture.
These lock in the shared contracts.
"""

from explorer import facets
from explorer.queries.reports import report_stmts


def _toggle_url(key, value=""):
    """Minimal stand-in for a page's facet_url(key, value) closure."""
    return f"?{key}={value}" if value else "?"


# ---------------------------------------------------------------------------
# facet_counts_group — single select
# ---------------------------------------------------------------------------
def test_single_select_items_in_master_order():
    """Items render in master order, filtered to values present in the pool,
    with active/count taken from current/counts."""
    group = facets.facet_counts_group(
        "theme",
        "Theme",
        "Filter by primary theme",
        [("a", "A"), ("b", "B"), ("c", "C")],
        {"a": 5, "c": 2},
        "c",
    )
    assert group is not None
    assert group["key"] == "theme"
    assert group["label"] == "Theme"
    assert group["aria_label"] == "Filter by primary theme"
    assert group["items"] == [
        {"value": "a", "name": "A", "count": 5, "active": False},
        {"value": "c", "name": "C", "count": 2, "active": True},
    ]


def test_single_select_accepts_dict_master():
    """Master entries may be dicts with value/name keys instead of tuples."""
    group = facets.facet_counts_group(
        "k",
        "L",
        "aria",
        [{"value": "a", "name": "A"}, {"value": "b", "name": "B"}],
        {"a": 1, "b": 2},
        "b",
    )
    assert group is not None
    assert [i["value"] for i in group["items"]] == ["a", "b"]
    assert group["items"][1]["active"] is True


def test_single_select_empty_pool_returns_none():
    """No pool values → None (the view drops the group)."""
    assert facets.facet_counts_group("k", "L", "aria", [("a", "A")], {}, None) is None


def test_single_select_proportions_optional():
    """proportion = count / max pool count, only when opted in."""
    group = facets.facet_counts_group(
        "k",
        "L",
        "aria",
        [("a", "A"), ("b", "B")],
        {"a": 10, "b": 5},
        None,
        proportions=True,
    )
    assert group is not None
    assert group["items"][0]["proportion"] == 1.0
    assert group["items"][1]["proportion"] == 0.5

    group = facets.facet_counts_group("k", "L", "aria", [("a", "A")], {"a": 1}, None)
    assert group is not None
    assert "proportion" not in group["items"][0]


def test_cutoff_toggle_wiring():
    """Items beyond cutoff get the extra flag; the group gains list_id /
    expanded / more with the shared toggle href."""
    master = [(str(i), str(i)) for i in range(5)]
    group = facets.facet_counts_group(
        "year",
        "Year",
        "Filter by year",
        master,
        {str(i): 1 for i in range(5)},
        "3",
        cutoff=2,
        toggle_base={"sort": "name", "dir": "asc"},
        toggle_param="years",
        toggle_label="years",
        expanded=False,
        list_id="year-facet-list",
    )
    assert group is not None
    assert [i["extra"] for i in group["items"]] == [False, False, True, True, True]
    assert group["list_id"] == "year-facet-list"
    assert group["expanded"] is False
    assert group["more"] == {
        "href": "?sort=name&dir=asc&years=all",
        "expanded": False,
        "count": 3,
        "label": "years",
        "param": "years",
    }


def test_cutoff_expanded_no_extra():
    """When expanded, no items are hidden and the toggle href collapses."""
    master = [(str(i), str(i)) for i in range(5)]
    group = facets.facet_counts_group(
        "year",
        "Year",
        "Filter by year",
        master,
        {str(i): 1 for i in range(5)},
        None,
        cutoff=2,
        toggle_base={"sort": "name", "dir": "asc", "years": "all"},
        toggle_param="years",
        expanded=True,
        list_id="year-facet-list",
    )
    assert group is not None
    assert [i["extra"] for i in group["items"]] == [False, False, False, False, False]
    assert group["more"]["href"] == "?sort=name&dir=asc"


def test_cutoff_short_list_no_toggle_wiring():
    """No toggle when the pool is at or under the cutoff."""
    master = [(str(i), str(i)) for i in range(3)]
    group = facets.facet_counts_group(
        "year",
        "Year",
        "Filter by year",
        master,
        {str(i): 1 for i in range(3)},
        None,
        cutoff=5,
        toggle_base={},
        toggle_param="years",
        expanded=False,
        list_id="year-facet-list",
    )
    assert group is not None
    # extra is always present when cutoff is configured — all False on a
    # short list, so nothing is hidden and there's nothing to toggle
    assert [i["extra"] for i in group["items"]] == [False, False, False]
    assert "more" not in group
    assert "list_id" not in group
    assert "expanded" not in group


def test_trailing_buckets_render_after_items():
    """trailing lands on the group verbatim — post-cutoff buckets that
    always render (temporal After/Before/No-year, links' No URL)."""
    group = facets.facet_counts_group(
        "temporal",
        "Temporal year",
        "Filter by temporal year",
        [("2020", "2020")],
        {"2020": 5},
        None,
        trailing=[{"value": "post", "name": "After 2026", "count": 3, "active": False}],
    )
    assert group is not None
    assert group["trailing"] == [{"value": "post", "name": "After 2026", "count": 3, "active": False}]
    assert "more" not in group


def test_always_render_returns_empty_group():
    """always_render keeps the group (empty items) even with an empty pool."""
    group = facets.facet_counts_group(
        "temporal",
        "Temporal year",
        "Filter by temporal year",
        [("2020", "2020")],
        {},
        None,
        always_render=True,
    )
    assert group is not None
    assert group["items"] == []


def test_search_config_lands_on_group():
    """search placeholder → the group gains a `search` key for the macro
    (opt-in: absent by default, so the other facet pages stay unchanged)."""
    group = facets.facet_counts_group(
        "publisher",
        "Publisher",
        "Filter by publisher",
        [("a", "A"), ("b", "B")],
        {"a": 5, "b": 2},
        None,
        search="Search publishers",
    )
    assert group is not None
    assert group["search"] == "Search publishers"

    plain = facets.facet_counts_group("k", "L", "aria", [("a", "A")], {"a": 1}, None)
    assert plain is not None
    assert "search" not in plain


# ---------------------------------------------------------------------------
# facet_counts_multiselect_group — organisations pubyear
# ---------------------------------------------------------------------------
def test_multiselect_no_selection_no_hrefs():
    """Nothing selected → no per-item hrefs (template falls back to the
    plain facet_url) and no active items."""
    group = facets.facet_counts_multiselect_group(
        "pubyear",
        "Year last published",
        "Filter by year last published",
        [("2020", "2020"), ("2019", "2019")],
        {"2020": 4, "2019": 2},
        None,
        facet_url=_toggle_url,
    )
    assert group is not None
    assert [i["active"] for i in group["items"]] == [False, False]
    assert all("href" not in i for i in group["items"])


def test_multiselect_toggle_add_and_remove():
    """Selected items' hrefs remove that value from the list; unselected
    items' hrefs add it."""
    group = facets.facet_counts_multiselect_group(
        "pubyear",
        "Year last published",
        "Filter by year last published",
        [("2020", "2020"), ("2019", "2019"), ("2018", "2018")],
        {"2020": 4, "2019": 2, "2018": 1},
        ("2020", "2019"),
        facet_url=_toggle_url,
    )
    assert group is not None
    items = {i["value"]: i for i in group["items"]}
    assert items["2020"]["href"] == "?pubyear=2019"
    assert items["2019"]["href"] == "?pubyear=2020"
    assert items["2018"]["href"] == "?pubyear=2018"
    assert [i["active"] for i in group["items"]] == [True, True, False]


def test_multiselect_removing_last_selection_clears():
    """Removing the last selected value clears the facet (empty value)."""
    group = facets.facet_counts_multiselect_group(
        "pubyear",
        "Year last published",
        "Filter by year last published",
        [("2020", "2020")],
        {"2020": 4},
        ("2020",),
        facet_url=_toggle_url,
    )
    assert group is not None
    assert group["items"][0]["href"] == "?"


def test_multiselect_proportions():
    group = facets.facet_counts_multiselect_group(
        "pubyear",
        "Year last published",
        "Filter by year last published",
        [("2020", "2020"), ("2019", "2019")],
        {"2020": 4, "2019": 2},
        None,
        facet_url=_toggle_url,
        proportions=True,
    )
    assert group is not None
    assert group["items"][0]["proportion"] == 1.0
    assert group["items"][1]["proportion"] == 0.5


def test_multiselect_empty_pool_returns_none():
    assert (
        facets.facet_counts_multiselect_group(
            "pubyear",
            "Year last published",
            "Filter by year last published",
            [("2020", "2020")],
            {},
            None,
            facet_url=_toggle_url,
        )
        is None
    )


def test_multiselect_trailing_lands_on_group():
    """trailing lands on the group verbatim — the orgs pubyear "Never
    published" bucket renders after the year items."""
    trailing = [
        {"value": "__none__", "name": "Never published", "count": 3, "active": False, "href": "?pubyear=__none__"},
    ]
    group = facets.facet_counts_multiselect_group(
        "pubyear",
        "Year last published",
        "Filter by year last published",
        [("2020", "2020")],
        {"2020": 4},
        ("2020",),
        facet_url=_toggle_url,
        trailing=trailing,
    )
    assert group is not None
    assert group["trailing"] == trailing


def test_multiselect_trailing_only_renders_group():
    """A group with only the trailing bucket (empty year pool) still
    renders — the never-published bucket must stay selectable even when no
    org has ever published."""
    trailing = [{"value": "__none__", "name": "Never published", "count": 3, "active": True, "href": "?"}]
    group = facets.facet_counts_multiselect_group(
        "pubyear",
        "Year last published",
        "Filter by year last published",
        [],
        {},
        ("__none__",),
        facet_url=_toggle_url,
        trailing=trailing,
    )
    assert group is not None
    assert group["items"] == []
    assert group["trailing"] == trailing


# ---------------------------------------------------------------------------
# report_stmts — facet filter substitution
# ---------------------------------------------------------------------------
def test_report_stmts_binds_selected_facet():
    """A selected facet substitutes its filter_sql into both statements and
    binds the value; with no selection the placeholder becomes empty."""
    report = {
        "count_sql": "SELECT COUNT(*) FROM t WHERE 1=1{org}",
        "list_sql": "SELECT id FROM t WHERE 1=1{org} ORDER BY id LIMIT %s OFFSET %s",
        "facets": [{"key": "org", "filter_sql": " AND org_slug = %s"}],
    }

    unfiltered = report_stmts(report)
    assert unfiltered["count"].sql == "SELECT COUNT(*) FROM t WHERE 1=1"
    assert unfiltered["params"] == []

    filtered = report_stmts(report, {"org": "abc"})
    assert filtered["count"].sql == "SELECT COUNT(*) FROM t WHERE 1=1 AND org_slug = %s"
    assert filtered["list"].sql == "SELECT id FROM t WHERE 1=1 AND org_slug = %s ORDER BY id LIMIT %s OFFSET %s"
    assert filtered["params"] == ["abc"]


# ---------------------------------------------------------------------------
# Query-string bookkeeping — the shared URL builders
# ---------------------------------------------------------------------------
def test_preserve_params_order_and_skips_empty():
    """sort/dir first, then each non-empty facet pair, then extras."""
    base = facets.preserve_params("name", "asc", [("theme", "transport"), ("source", ""), ("links", "0")])
    assert base == {"sort": "name", "dir": "asc", "theme": "transport", "links": "0"}
    assert facets.preserve_params("name", "asc", [], extras={"formats": "all"}) == {
        "sort": "name",
        "dir": "asc",
        "formats": "all",
    }


def test_preserve_params_omits_default_sort():
    """A default sort is left out of the base so links stay clean; a
    non-default sort is still preserved. Covers the sort-only facade
    (facets.sort_params) the facet-less pages' pagers use."""
    assert facets.preserve_params("views", "desc", [("theme", "transport")], defaults=("views", "desc")) == {
        "theme": "transport",
    }
    assert facets.preserve_params("title", "asc", [("theme", "transport")], defaults=("views", "desc")) == {
        "sort": "title",
        "dir": "asc",
        "theme": "transport",
    }
    # Same sort but the opposite direction is not the default either.
    assert facets.preserve_params("views", "asc", [], defaults=("views", "desc")) == {
        "sort": "views",
        "dir": "asc",
    }
    # sort_params is the no-facet case of the same rule.
    assert facets.sort_params("dataset_count", "desc", ("dataset_count", "desc")) == {}
    assert facets.sort_params("root_title", "asc", ("dataset_count", "desc")) == {
        "sort": "root_title",
        "dir": "asc",
    }


def test_facet_url_for_sets_and_clears_one_value():
    facet_url = facets.facet_url_for({"sort": "name", "dir": "asc", "theme": "transport"})
    assert facet_url("theme", "") == "?sort=name&dir=asc"
    assert facet_url("source", "manual") == "?sort=name&dir=asc&theme=transport&source=manual"
    assert facets.facet_url_for({})("x", "y") == "?x=y"
    assert facets.facet_url_for({})("x", "") == "?"


def test_facet_qs_and_pager_base_optionally_drop_sort():
    base = {"sort": "name", "dir": "asc", "theme": "transport"}
    assert facets.facet_qs(base) == "&sort=name&dir=asc&theme=transport"
    assert facets.facet_qs(base, include_sort=False) == "&theme=transport"
    assert facets.facet_qs({}, include_sort=False) == ""
    assert facets.pager_base(base) == "?sort=name&dir=asc&theme=transport"
    assert facets.pager_base(base, include_sort=False) == "?theme=transport"
    # no state left → clean ?page=N base
    assert facets.pager_base({"sort": "name", "dir": "asc"}, include_sort=False) == ""
    assert facets.pager_base({}) == ""


def test_facet_toggle_url_expands_and_collapses():
    base = {"sort": "name", "dir": "asc", "theme": "transport"}
    assert facets.facet_toggle_url(base, "publishers", expanded=True) == (
        "?sort=name&dir=asc&theme=transport&publishers=all"
    )
    assert facets.facet_toggle_url({**base, "publishers": "all"}, "publishers", expanded=False) == (
        "?sort=name&dir=asc&theme=transport"
    )
    assert facets.facet_toggle_url({}, "publishers", expanded=False) == "?"
