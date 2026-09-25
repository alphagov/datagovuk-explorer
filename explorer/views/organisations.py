"""GET /organisations — all organisations, with facets and server-side
sorting.

Facets: ?created_year=YYYY, ?last_published_year=YYYY[,YYYY] (or __none__ for
orgs that have never published), ?datasets=<bucket>.
"""

from dataclasses import dataclass

from django.shortcuts import render

from explorer import facets
from explorer.helpers import format_date
from explorer.queries.organisations import (
    DATASET_BUCKET_NAMES,
    DATASET_BUCKETS,
    ORG_SORT,
    ORG_SORT_DEFAULT,
    VALID_DATASET_BUCKETS,
    all_org_rows,
    org_aggregate_rows,
    org_created_years,
    organisations_facet_counts,
    organisations_stmts,
)
from explorer.sort import parse_sort

from .core import paginate, pill


def _merge_org_rows(org_rows, agg_rows) -> list[dict]:
    """Merge the org rows with their per-org aggregates into display rows.
    Orgs absent from agg_rows have no datasets."""
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
            },
        )
    return rows


def _page_row(r: dict) -> dict:
    """One SQL page row → display row, minus the year fields the filters
    don't display."""
    return {
        "slug": r["slug"],
        "name": r["display_name"] or r["title"] or r["name"],
        "dataset_count": r["package_count"] or 0,
        "resource_count": r["total_resources"] or 0,
        "views": r["total_views"] or 0,
        "link_health": r["link_health"],
        "type": r["type"],
        "state": r["state"],
        "created": format_date(r["created"]),
        "last_published": format_date(r["last_published"]),
    }


@dataclass(frozen=True)
class OrgFilters:
    created_year: str | None
    last_published_years: tuple[str, ...] | None
    datasets: str | None


def _parse_filters(request, valid_created_years, valid_pub_years) -> OrgFilters:
    """Validate the facet selections from request.GET."""
    created_year = request.GET.get("created_year")
    current_created_year = created_year if created_year in valid_created_years else None

    last_published_year = request.GET.get("last_published_year")
    current_pub_years = None
    if last_published_year is not None:
        py = last_published_year.split(",")
        # __none__ (never published) is mutually exclusive with real years
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
    # Memoised fetches feed the facet pools and the year whitelist; only the
    # page list is fetched per request.
    org_rows = all_org_rows()
    agg_rows = org_aggregate_rows()
    rows = _merge_org_rows(org_rows, agg_rows)

    sort, dir_ = parse_sort(request, ORG_SORT, *ORG_SORT_DEFAULT)

    created_years = org_created_years()
    last_published_years = sorted(
        {o["last_published_year"] for o in rows if o["last_published_year"]},
        reverse=True,
    )

    filters = _parse_filters(request, set(created_years), set(last_published_years))

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
        _page_row(r) for r in stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])
    ]

    last_published_param = ",".join(filters.last_published_years) if filters.last_published_years else None

    # Year lists collapse behind their "More" toggles (?created_years=all).
    created_year_expanded = request.GET.get("created_years") == "all"
    last_published_year_expanded = request.GET.get("last_published_years") == "all"
    expanded_extras = {}
    if created_year_expanded:
        expanded_extras["created_years"] = "all"
    if last_published_year_expanded:
        expanded_extras["last_published_years"] = "all"

    # Base query string for facet/sort/pager links: sort, dir, active facets,
    # then the expanded-list extras so open lists stay open.
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("created_year", filters.created_year),
            ("last_published_year", last_published_param),
            ("datasets", filters.datasets),
        ],
        expanded_extras or None,
        defaults=ORG_SORT_DEFAULT,
    )
    facet_url = facets.facet_url_for(base_params)

    # sort_link/pagination append ?sort=..&dir=.. themselves, so drop them here.
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    facet_counts = organisations_facet_counts(
        {
            "created_year": filters.created_year,
            "last_published_year": filters.last_published_years,
            "datasets": filters.datasets,
        },
    )
    bucket_counts = {r["bucket"]: r["count"] for r in facet_counts["datasets"]}
    year_pool_counts = {r["created_year"]: r["count"] for r in facet_counts["created_years"]}
    pub_year_pool_counts = {r["last_published_year"]: r["count"] for r in facet_counts["last_published_years"]}

    # "Never published" bucket: toggling __none__ replaces any selected years.
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

    facet_groups = {
        g["key"]: g
        for g in (
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
        if g is not None
    }

    last_published_label = (
        "Never published"
        if filters.last_published_years == ("__none__",)
        else ", ".join(filters.last_published_years)
        if filters.last_published_years
        else None
    )
    pills = [
        pill("Datasets", DATASET_BUCKET_NAMES[filters.datasets], facet_url("datasets", ""))
        if filters.datasets
        else None,
        pill("Created year", filters.created_year, facet_url("created_year", "")) if filters.created_year else None,
        pill("Published in", last_published_label, facet_url("last_published_year", ""))
        if filters.last_published_years
        else None,
    ]

    return render(
        request,
        "organisations.html",
        {
            "title": "data.gov.uk — Explorer",
            "nav_key": "orgs",
            "orgs": page_rows,
            "shown_orgs": shown_orgs,
            "sort": sort,
            "dir": dir_,
            "pills": pills,
            "facet_groups": facet_groups,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
            **pagination,
        },
    )
