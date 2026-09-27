"""GET /organisations/reviews — per-publisher average review scores."""

from django.shortcuts import render

from explorer import facets
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


def publisher_reviews(request):
    datasets = request.GET.get("datasets")
    filters: dict[str, str] = {}
    if datasets in VALID_DATASET_BUCKETS:
        filters["datasets"] = datasets

    sort, dir_ = parse_sort(request, PUBLISHER_REVIEWS_SORT, *PUBLISHER_REVIEWS_SORT_DEFAULT)

    stmts = publisher_reviews_stmts(filters, sort, dir_)
    total = stmts["count"].get(*stmts["params"])["n"]

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
            **pagination,
        },
    )
