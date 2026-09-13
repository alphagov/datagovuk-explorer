"""GET /series — list all detected series (paginated, sortable via ?sort= & ?dir=)
GET /series/{id} — show all datasets in one series.

The list-statement builder lives in explorer/queries/series.py
(series_list_stmt).
"""

import re

from django.shortcuts import render

from explorer import facets
from explorer.queries.series import (
    SERIES_BY_ID,
    SERIES_COUNT,
    SERIES_DATASETS,
    SERIES_SORT,
    SERIES_SORT_DEFAULT,
    series_built,
    series_list_stmt,
)
from explorer.sort import parse_sort

from .core import paginate

# Leading digits, stop at the first non-digit (so "/series/12.5" reads as
# 12, not a 404).
_LEADING_DIGITS = re.compile(r"\d+")


def series_list(request):
    """GET /series — paginated, sortable list of detected series."""
    # The series tables always exist (migrations own the schema), but
    # "not built" means empty — show the "not built" 404.
    if not series_built():
        return render(
            request,
            "404.html",
            {"title": "Series data not built yet"},
            status=404,
        )

    total = SERIES_COUNT.get()["n"]
    pagination = paginate(request, total)

    sort, dir_ = parse_sort(request, SERIES_SORT, *SERIES_SORT_DEFAULT)
    pager_base = facets.pager_base(facets.sort_params(sort, dir_, SERIES_SORT_DEFAULT))

    series = series_list_stmt(sort, dir_).all(pagination["page_size"], pagination["offset"])

    return render(
        request,
        "series.html",
        {
            "title": "Series — data.gov.uk Explorer",
            "section": "datasets",
            "series": series,
            "total": total,
            **pagination,
            "pager_base": pager_base,
            "sort": sort,
            "dir": dir_,
        },
    )


def series_detail(request, series_id):
    """GET /series/{id} — all datasets in one series."""
    if not series_built():
        return render(
            request,
            "404.html",
            {"title": "Series data not built yet"},
            status=404,
        )

    m = _LEADING_DIGITS.match(series_id)
    if not m:
        return render(request, "404.html", {"title": "Page not found"}, status=404)
    id_ = int(m.group(0))

    s = SERIES_BY_ID.get(id_)
    if not s:
        return render(request, "404.html", {"title": "Series not found"}, status=404)

    # Small list (at most a few hundred datasets per series) — no pager.
    datasets = SERIES_DATASETS.all(id_)

    return render(
        request,
        "series_detail.html",
        {
            "title": f"{s['root_title']} — Series — data.gov.uk Explorer",
            "section": "datasets",
            "series": s,
            "datasets": datasets,
        },
    )
