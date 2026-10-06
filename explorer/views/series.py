"""GET /series — list all detected series (paginated, sortable via ?sort= & ?dir=)
GET /series/{id} — show all datasets in one series.

The list-statement builder lives in explorer/queries/series.py
(series_list_stmt).
"""

import re

from django.shortcuts import render

from explorer import facets
from explorer.csv_export import csv_filename, csv_response
from explorer.queries.core import iter_rows
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


def _not_built(request):
    """The shared "series not built" 404 — the tables always exist
    (migrations own the schema), but empty means the pipeline hasn't run."""
    return render(request, "404.html", {"title": "Series data not built yet"}, status=404)


def _listing(request) -> dict:
    """Resolve one /series request into its sort state and compiled count +
    list statement — shared by the page and the CSV download."""
    sort, dir_ = parse_sort(request, SERIES_SORT, *SERIES_SORT_DEFAULT)
    return {
        "sort": sort,
        "dir": dir_,
        "stmts": {"params": [], "count": SERIES_COUNT, "list": series_list_stmt(sort, dir_)},
        "total": SERIES_COUNT.get()["n"],
    }


# CSV export columns — the table's own columns (Type is the badge's label),
# then the series id (the /series/{id} link key) last. A series is derived,
# so it has no CKAN GUID; the integer id is its only identifier.
_SERIES_CSV_COLUMNS = [
    ("Title", "root_title"),
    ("Type", "type"),
    ("Datasets", "dataset_count"),
    ("Orgs", "org_count"),
    ("Series ID", "id"),
]


def _csv_row(r: dict) -> dict:
    """One SQL row → its export shape: the Type label the badge renders
    plus the series id."""
    return {
        "root_title": r["root_title"],
        "type": "Template" if r["type"] == "template" else "Timeseries",
        "dataset_count": r["dataset_count"],
        "org_count": r["org_count"],
        "id": r["id"],
    }


def series_list(request):
    """GET /series — paginated, sortable list of detected series."""
    if not series_built():
        return _not_built(request)

    listing = _listing(request)
    total = listing["total"]
    pagination = paginate(request, total)

    sort, dir_ = listing["sort"], listing["dir"]
    pager_base = facets.pager_base(facets.sort_params(sort, dir_, SERIES_SORT_DEFAULT))

    series = listing["stmts"]["list"].all(pagination["page_size"], pagination["offset"])

    return render(
        request,
        "series.html",
        {
            "title": "Series — data.gov.uk Explorer",
            "nav_key": "series",
            "series": series,
            "total": total,
            **pagination,
            "pager_base": pager_base,
            "download_url": f"/series/download.csv{pager_base}",
            "sort": sort,
            "dir": dir_,
        },
    )


def series_download(request):
    """GET /series/download.csv — the same sorted series as the table,
    unpaginated and as a CSV attachment."""
    if not series_built():
        return _not_built(request)
    listing = _listing(request)
    rows = (_csv_row(r) for r in iter_rows(listing["stmts"]))
    return csv_response(csv_filename("series"), _SERIES_CSV_COLUMNS, rows)


def series_detail(request, series_id):
    """GET /series/{id} — all datasets in one series."""
    if not series_built():
        return _not_built(request)

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
            "nav_key": "series-detail",
            "series": s,
            "datasets": datasets,
        },
    )
