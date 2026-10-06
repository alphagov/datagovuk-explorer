"""GET /reviews — list of LLM-reviewed datasets, read from the reviews
    table (populated by scripts/llm/ingest_reviews.py). Sorted
    worst-first by default so quality problems surface first; every column
    is sortable via ?sort=&dir=, and the sidebar facets filter by each
    score group (?findability=, ?resources=).

The page list, count, sort and facet counts all run in SQL (the shared
reviews_stmts/reviews_facet_counts builders in explorer/queries/reviews.py
— the /datasets pattern), so only the page's rows are fetched, not the
whole reviews table. Title/org come from the current datasets row via the
join, not review-time values from the JSON.
"""

from django.shortcuts import render

from explorer import facets
from explorer.csv_export import csv_response
from explorer.queries.core import iter_rows
from explorer.queries.reviews import (
    FACET_KEYS,
    REVIEWS_SORT,
    REVIEWS_SORT_DEFAULT,
    SCORE_KEYS,
    SCORE_VALUES,
    reviews_facet_counts,
    reviews_stmts,
)
from explorer.sort import parse_sort

from .core import paginate, pill

# Score dimensions in sidebar order — the facet-group labels for the
# pools computed in SQL (queries/reviews.py owns the keys/clauses).
SCORE_GROUPS = [
    {"key": "findability", "label": "Description"},
    {"key": "resources", "label": "Links"},
]


def _score_facet_group(key: str, label: str, counts: dict, current: str | None) -> dict | None:
    """One score facet group from the SQL pool counts — the values present
    in the data, scaled proportion bars, plus the "No score" trailing
    bucket when any review in the pool is missing that score. None when
    the pool is empty."""
    no_score = counts.pop("__none__", 0)
    pool = counts  # values only, __none__ removed above
    trailing = None
    if no_score:
        pool_max = max([*pool.values(), no_score, 1])
        trailing = [
            {
                "value": "none",
                "name": "No score",
                "count": no_score,
                "active": current == "none",
                "proportion": no_score / pool_max,
            },
        ]
    return facets.facet_counts_group(
        key,
        label,
        f"Filter by {label.lower()} score",
        [(v, f"{v}/5") for v in SCORE_VALUES],
        pool,
        current,
        proportions=True,
        trailing=trailing,
    )


def _listing(request) -> dict:
    """Resolve one /reviews request into its validated filters, sort state
    and compiled count+list statements — shared by the page and the CSV
    download so the exported rows match the table."""
    # Current facet selections — single-select per group, combinable across
    # groups. Score values must be a valid score or "none"; publisher is an
    # org slug validated against the unfiltered facet pool.
    filters: dict[str, str] = {}
    for key in SCORE_KEYS:
        v = request.GET.get(key)
        if v == "none" or v in SCORE_VALUES:
            filters[key] = v

    # Publisher validation: the unfiltered pool (cached after first call)
    # supplies the whitelist of valid org slugs.
    valid_publishers = {p["value"] for p in reviews_facet_counts({})["publishers"]}
    publisher = request.GET.get("publisher")
    if publisher in valid_publishers:
        filters["publisher"] = publisher

    sort, dir_ = parse_sort(request, REVIEWS_SORT, *REVIEWS_SORT_DEFAULT)
    stmts = reviews_stmts(filters, sort, dir_)
    return {
        "filters": filters,
        "sort": sort,
        "dir": dir_,
        "stmts": stmts,
        "total": stmts["count"].get(*stmts["params"])["n"],
    }


# CSV export columns — the table's own columns then the dataset GUID last.
# Scores export as raw numbers (the table renders them as "n/5").
_REVIEWS_CSV_COLUMNS = [
    ("Dataset", "title"),
    ("Publisher", "org_display_name"),
    ("Description", "findability"),
    ("Links", "resources"),
    ("Dataset ID", "ckan_id"),
]


def reviews(request):
    """GET /reviews — the LLM review table with per-score facets."""
    listing = _listing(request)
    filters, sort, dir_ = listing["filters"], listing["sort"], listing["dir"]

    facet_counts = reviews_facet_counts(filters)
    publisher_pool = facet_counts["publishers"]

    publisher_expanded = request.GET.get("publishers") == "all"
    expanded_extras: dict[str, str] = {}
    if publisher_expanded:
        expanded_extras["publishers"] = "all"

    # Shared query-string machinery from explorer/facets.py: the base keeps
    # sort/dir then the active facets in FACET_KEYS order; facet_qs drops
    # sort/dir for the sort/pagination links; facet_url sets or clears one
    # facet value (empty value clears it, back to the pills).
    base_params = facets.preserve_params(
        sort,
        dir_,
        [(k, filters.get(k, "")) for k in FACET_KEYS],
        extras=expanded_extras,
        defaults=REVIEWS_SORT_DEFAULT,
    )
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    # Reviews matching all active filters — count + page in SQL (only the
    # page's rows are fetched).
    stmts = listing["stmts"]
    shown_count = listing["total"]

    pagination = paginate(request, shown_count)
    page_reviews = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

    # Sidebar facet groups — publisher + each score group counts over the
    # pool filtered by every other group (the standard self-excluding sidebar).
    publisher_names = {p["value"]: p["name"] for p in publisher_pool}
    facet_groups = {}

    publisher_group = facets.facet_counts_group(
        "publisher",
        "Publisher",
        "Filter by publisher",
        [(p["value"], p["name"]) for p in publisher_pool],
        {p["value"]: p["count"] for p in publisher_pool},
        filters.get("publisher"),
        proportions=True,
        plural="publishers",
        toggle_base=base_params,
        expanded=publisher_expanded,
        search="Search publishers",
    )
    if publisher_group is not None:
        facet_groups[publisher_group["key"]] = publisher_group

    for g in SCORE_GROUPS:
        group = _score_facet_group(g["key"], g["label"], facet_counts[g["key"]], filters.get(g["key"]))
        if group is not None:
            facet_groups[group["key"]] = group

    publisher_label = (
        publisher_names.get(filters.get("publisher"), filters.get("publisher")) if filters.get("publisher") else None
    )
    pills = [
        pill("Publisher", publisher_label, facet_url("publisher", "")) if filters.get("publisher") else None,
        *[
            pill(
                g["label"],
                "No score" if filters.get(g["key"]) == "none" else f"{filters[g['key']]}/5",
                facet_url(g["key"], ""),
            )
            if filters.get(g["key"])
            else None
            for g in SCORE_GROUPS
        ],
    ]

    return render(
        request,
        "reviews.html",
        {
            "title": f"Dataset reviews ({shown_count})",
            "nav_key": "reviews",
            "reviews": page_reviews,
            "total": shown_count,
            "shown": shown_count,
            **pagination,
            "sort": sort,
            "dir": dir_,
            "facet_groups": facet_groups,
            "pills": pills,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
            "download_url": f"/reviews/download.csv{pager_base}",
        },
    )


def reviews_download(request):
    """GET /reviews/download.csv — the same filtered, sorted reviews as the
    table, unpaginated and as a CSV attachment."""
    listing = _listing(request)
    return csv_response("reviews.csv", _REVIEWS_CSV_COLUMNS, iter_rows(listing["stmts"]))
