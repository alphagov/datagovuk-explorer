"""GET /organisations — all organisations (server-side sortable, facet
filters).

Facets use the same pattern as /datasets:
  ?created_year=YYYY     — year created (single-select, years from the
                          chart data)
  ?last_published_year=YYYY[,YYYY] — year last published (comma-separated
                    multi-select; __none__ selects orgs that have never
                    published)
  ?datasets=...  — dataset-count bucket (0|1-10|11-50|51-100|101-500|501-1000|1000+)

Sidebar facet counts are self-excluding SQL aggregates from
queries/organisations.py (organisations_facet_counts) — each group counts
over the pool filtered by the other two groups, exactly like /datasets.
The page list/filter/sort/pagination is SQL (organisations_stmts — one
count + one page per request); the memoised full fetch still feeds the
facet master lists, the last-published-year validation whitelist and the
sidebar pools.

Sort columns are whitelisted in explorer.sort.SORT_COLUMNS; unknown keys
fall back to the default (name asc).
"""

from dataclasses import dataclass

from django.shortcuts import render

from explorer import facets
from explorer.helpers import format_date
from explorer.queries.organisations import (
    DATASET_BUCKET_NAMES,
    DATASET_BUCKETS,
    VALID_DATASET_BUCKETS,
    all_org_rows,
    org_aggregate_rows,
    organisations_facet_counts,
    organisations_stmts,
    yearly_org_counts,
)
from explorer.sort import SORT_COLUMNS

from .core import _sort_dir, paginate


def _merge_org_rows(org_rows, agg_rows) -> list[dict]:
    """Merge the org rows with the one-per-org aggregate pass into display
    rows. Owns the format_date / last_published_year / has_data
    computations. Any org_slug in agg_rows has at least one dataset, so the
    slug set doubles as the fetched-slugs set."""
    fetched_slugs = {r["org_slug"] for r in agg_rows}
    resources_by_org = {r["org_slug"]: r["total_resources"] for r in agg_rows}
    views_by_org = {r["org_slug"]: r["total_views"] for r in agg_rows}
    last_published_by_org = {r["org_slug"]: r["last_published"] for r in agg_rows}

    rows = []
    for o in org_rows:
        last_pub = last_published_by_org.get(o["slug"])
        rows.append(
            {
                "slug": o["slug"],
                "name": o["display_name"] or o["title"] or o["name"],
                "dataset_count": o["package_count"] or 0,
                "resource_count": resources_by_org.get(o["slug"]) or 0,
                "views": views_by_org.get(o["slug"]) or 0,
                "type": o["type"],
                "state": o["state"],
                "approval_status": o["approval_status"],
                "created": format_date(o["created"]),
                "created_year": o["created"][:4] if o["created"] else None,
                "last_published": format_date(last_pub),
                "last_published_year": last_pub[:4] if last_pub else None,
                "has_data": o["slug"] in fetched_slugs,
            },
        )
    return rows


def _page_row(r: dict) -> dict:
    """One SQL page row → display row — the same fields _merge_org_rows
    produces for the table (minus created_year/last_published_year, which
    the page filters don't display). has_data comes from the aggregate
    join: an org is in it iff it has at least one dataset."""
    return {
        "slug": r["slug"],
        "name": r["display_name"] or r["title"] or r["name"],
        "dataset_count": r["package_count"] or 0,
        "resource_count": r["total_resources"] or 0,
        "views": r["total_views"] or 0,
        "type": r["type"],
        "state": r["state"],
        "approval_status": r["approval_status"],
        "created": format_date(r["created"]),
        "last_published": format_date(r["last_published"]),
        "has_data": r["has_data"],
    }


@dataclass(frozen=True)
class OrgFilters:
    """The three validated /organisations facet selections (None = not
    active). last_published_years is the multi-select tuple."""

    created_year: str | None
    last_published_years: tuple[str, ...] | None
    datasets: str | None


def _parse_filters(request, valid_created_years, valid_pub_years) -> OrgFilters:
    """Validate the /organisations facet selections from request.GET.

    created_year is single-select; last_published_year is a comma-separated
    multi-select (every value must be a valid year, or the selection must
    be exactly the never-published marker __none__ — never-published orgs
    are mutually exclusive with any real year, so mixed selections are
    rejected); datasets is a bucket key from VALID_DATASET_BUCKETS.
    """
    created_year = request.GET.get("created_year")
    current_created_year = created_year if created_year in valid_created_years else None

    last_published_year = request.GET.get("last_published_year")
    current_pub_years = None
    if last_published_year is not None:
        py = last_published_year.split(",")
        if py == ["__none__"]:
            current_pub_years = ("__none__",)
        elif py and all(y in valid_pub_years for y in py):
            current_pub_years = tuple(py)

    datasets = request.GET.get("datasets")
    current_datasets = datasets if datasets in VALID_DATASET_BUCKETS else None

    return OrgFilters(
        created_year=current_created_year,
        last_published_years=current_pub_years,
        datasets=current_datasets,
    )


def organisations(request):
    """GET /organisations — all orgs, server-side sortable, with facets."""
    # The memoised fetches (queries/organisations.py) feed the facet master
    # lists, the pub-year validation whitelist and the sidebar pools; only
    # the page list is fetched per request (SQL, one page of 100).
    org_rows = all_org_rows()
    agg_rows = org_aggregate_rows()
    yearly = yearly_org_counts()

    rows = _merge_org_rows(org_rows, agg_rows)

    sort, dir_ = _sort_dir(request, SORT_COLUMNS, "name")

    # Facet master lists — the validation whitelists and the facet builders
    # consume these (computed once, not per consumer). Created years come
    # from the chart data; last-published years from the merged rows.
    created_years = [y["year"] for y in yearly][::-1]
    last_published_years = sorted(
        {o["last_published_year"] for o in rows if o["last_published_year"]},
        reverse=True,
    )

    filters = _parse_filters(request, set(created_years), set(last_published_years))

    # Count + page in SQL — filters and ORDER BY come from
    # queries/organisations.py.
    stmts = organisations_stmts(
        {
            "created_year": filters.created_year,
            "last_published_year": filters.last_published_years,
            "datasets": filters.datasets,
        },
        sort,
        dir_,
    )
    shown_orgs = stmts["count"].get(*stmts["params"])["n"]
    pagination = paginate(request, shown_orgs)
    page_rows = [
        _page_row(r)
        for r in stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])
    ]

    last_published_param = ",".join(filters.last_published_years) if filters.last_published_years else None

    # Both year lists also collapse past the default cutoff behind their
    # own More toggles (?created_years=all / ?last_published_years=all).
    created_year_expanded = request.GET.get("created_years") == "all"
    last_published_year_expanded = request.GET.get("last_published_years") == "all"
    expanded_extras = {}
    if created_year_expanded:
        expanded_extras["created_years"] = "all"
    if last_published_year_expanded:
        expanded_extras["last_published_years"] = "all"

    # Shared query-string base: sort, dir, then the active facets (created
    # year, last published year, datasets) in a fixed order, then the
    # expanded-lists extras so facet/sort/pager links keep the lists open.
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("created_year", filters.created_year),
            ("last_published_year", last_published_param),
            ("datasets", filters.datasets),
        ],
        expanded_extras or None,
    )
    facet_url = facets.facet_url_for(base_params)

    # Fragment for sort/pagination links — the sort_link/pagination macros
    # append it to ?sort=..&dir=.., so sort/dir come off here.
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Sidebar facet groups (pool counts + current selection -> group).
    # Counts are self-excluding SQL aggregates (each group applies the other
    # two filters, omitting its own) via the shared core.facet_where helper;
    # the shared builders only assemble them into items.
    facet_counts = organisations_facet_counts(
        {
            "created_year": filters.created_year,
            "last_published_year": filters.last_published_years,
            "datasets": filters.datasets,
        },
    )
    bucket_counts = {r["bucket"]: r["count"] for r in facet_counts["datasets"]}
    year_pool_counts = {r["created_year"]: r["count"] for r in facet_counts["created_years"]}
    pub_year_pool_counts = {
        r["last_published_year"]: r["count"] for r in facet_counts["last_published_years"]
    }

    # The last-published facet's trailing bucket — orgs that have never
    # published (no datasets at all). Its href toggles __none__ in the
    # selection: clicking it replaces any selected years (an org either has
    # a last-published year or it doesn't), clicking it again clears the
    # facet.
    pubyear_trailing = []
    if facet_counts["no_last_published_year"]:
        pubyear_trailing.append(
            {
                "value": "__none__",
                "name": "Never published",
                "count": facet_counts["no_last_published_year"],
                "active": filters.last_published_years == ("__none__",),
                "href": (
                    facet_url("last_published_year", "")
                    if filters.last_published_years == ("__none__",)
                    else facet_url("last_published_year", "__none__")
                ),
            },
        )

    facet_groups = [
        group
        for group in (
            facets.facet_counts_group(
                "datasets",
                "Datasets",
                "Filter by number of datasets",
                [(value, name) for value, name in DATASET_BUCKETS],
                bucket_counts,
                filters.datasets,
                proportions=True,
            ),
            facets.facet_counts_group(
                "created_year",
                "Year created",
                "Filter by year created",
                [(y, y) for y in created_years],
                year_pool_counts,
                filters.created_year,
                proportions=True,
                plural="created years",
                toggle_base=base_params,
                expanded=created_year_expanded,
            ),
            facets.facet_counts_multiselect_group(
                "last_published_year",
                "Year last published",
                "Filter by year last published",
                [(y, y) for y in last_published_years],
                pub_year_pool_counts,
                filters.last_published_years,
                facet_url=facet_url,
                proportions=True,
                plural="last published years",
                toggle_base=base_params,
                expanded=last_published_year_expanded,
                trailing=pubyear_trailing or None,
            ),
        )
        if group is not None
    ]

    return render(
        request,
        "organisations.html",
        {
            "title": "data.gov.uk — Explorer",
            "section": "orgs",
            "orgs": page_rows,
            "shown_orgs": shown_orgs,
            "sort": sort,
            "dir": dir_,
            "yearly": yearly,
            "created_year": filters.created_year,
            "last_published_year": (
                "Never published"
                if filters.last_published_years == ("__none__",)
                else ", ".join(filters.last_published_years)
                if filters.last_published_years
                else None
            ),
            "datasets": filters.datasets,
            "datasets_label": (DATASET_BUCKET_NAMES[filters.datasets] if filters.datasets else None),
            "facet_groups": facet_groups,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
            **pagination,
        },
    )
