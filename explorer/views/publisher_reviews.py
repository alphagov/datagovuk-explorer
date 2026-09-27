"""GET /organisations/reviews — per-publisher average review scores."""

from django.shortcuts import render

from explorer import facets
from explorer.queries.organisations import (
    PUBLISHER_REVIEWS_SORT,
    PUBLISHER_REVIEWS_SORT_DEFAULT,
    publisher_reviews_stmts,
)
from explorer.sort import parse_sort

from .core import paginate


def publisher_reviews(request):
    sort, dir_ = parse_sort(request, PUBLISHER_REVIEWS_SORT, *PUBLISHER_REVIEWS_SORT_DEFAULT)

    stmts = publisher_reviews_stmts(sort, dir_)
    total = stmts["count"].get(*stmts["params"])["n"]

    pagination = paginate(request, total)
    rows = stmts["list"].all(*stmts["params"], pagination["page_size"], pagination["offset"])

    base_params = facets.preserve_params(sort, dir_, [], defaults=PUBLISHER_REVIEWS_SORT_DEFAULT)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

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
            "facet_qs": facet_qs,
            "pager_base": pager_base,
            **pagination,
        },
    )
