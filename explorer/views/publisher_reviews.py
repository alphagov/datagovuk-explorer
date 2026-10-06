"""GET /organisations/reviews — per-publisher average review scores."""

from django.shortcuts import render

from explorer import facets
from explorer.csv_export import csv_filename, csv_response
from explorer.queries.core import iter_rows
from explorer.queries.organisations import (
    DATASET_BUCKET_NAMES,
    DATASET_BUCKETS,
    PUBLISHER_REVIEWS_SORT,
    PUBLISHER_REVIEWS_SORT_DEFAULT,
    VALID_DATASET_BUCKETS,
    publisher_reviews_facet_counts,
    publisher_reviews_stmts,
)
from explorer.sort import parse_sort

from .core import paginate, pill

# CSV export columns — the table's own columns (the table's "Description"/
# "Links" headers are the avg_findability/avg_resources scores), then the
# publisher's CKAN org UUID last.
_PUBLISHER_REVIEWS_CSV_COLUMNS = [
    ("Publisher", "name"),
    ("Datasets", "reviewed_datasets"),
    ("Description", "avg_findability"),
    ("Links", "avg_resources"),
    ("Publisher ID", "ckan_id"),
]


def _listing(request) -> dict:
    """Resolve one /organisations/reviews request into its filter/sort state
    and compiled count+list statements — shared by the page and the CSV
    download so the exported rows match the table."""
    datasets = request.GET.get("datasets")
    filters: dict[str, str] = {}
    if datasets in VALID_DATASET_BUCKETS:
        filters["datasets"] = datasets

    sort, dir_ = parse_sort(request, PUBLISHER_REVIEWS_SORT, *PUBLISHER_REVIEWS_SORT_DEFAULT)
    stmts = publisher_reviews_stmts(filters, sort, dir_)
    return {
        "filters": filters,
        "sort": sort,
        "dir": dir_,
        "stmts": stmts,
        "total": stmts["count"].get(*stmts["params"])["n"],
    }


def publisher_reviews(request):
    listing = _listing(request)
    filters, sort, dir_ = listing["filters"], listing["sort"], listing["dir"]
    stmts = listing["stmts"]
    total = listing["total"]

    pagination = paginate(request, total)
    rows = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

    base_params = facets.preserve_params(
        sort,
        dir_,
        [("datasets", filters.get("datasets", ""))],
        defaults=PUBLISHER_REVIEWS_SORT_DEFAULT,
    )
    facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    fc = publisher_reviews_facet_counts(filters)
    bucket_counts = {r["bucket"]: r["count"] for r in fc["datasets"]}

    facet_groups = {}
    group = facets.facet_counts_group(
        "datasets",
        "Reviewed datasets",
        "Filter by number of reviewed datasets",
        [(value, name) for value, name in DATASET_BUCKETS],
        bucket_counts,
        filters.get("datasets"),
        proportions=True,
    )
    if group is not None:
        facet_groups[group["key"]] = group

    pills = [
        pill("Datasets", DATASET_BUCKET_NAMES[filters["datasets"]], facet_url("datasets", ""))
        if filters.get("datasets")
        else None,
    ]

    return render(
        request,
        "publisher_reviews.html",
        {
            "title": "Publisher reviews — data.gov.uk Explorer",
            "nav_key": "publisher_reviews",
            "rows": rows,
            "shown": total,
            "sort": sort,
            "dir": dir_,
            "facet_groups": facet_groups,
            "facet_url": facet_url,
            "pills": pills,
            "facet_qs": facet_qs,
            "pager_base": pager_base,
            "download_url": f"/organisations/reviews/download.csv{pager_base}",
            **pagination,
        },
    )


def publisher_reviews_download(request):
    """GET /organisations/reviews/download.csv — the same filtered, sorted
    publishers as the table, unpaginated and as a CSV attachment."""
    listing = _listing(request)
    stmts = listing["stmts"]
    rows = iter_rows(stmts)
    return csv_response(csv_filename("publisher-reviews", listing["filters"]), _PUBLISHER_REVIEWS_CSV_COLUMNS, rows)
