"""Shared sort helpers for every sortable page.

Each page defines a dict of column keys -> SQL ORDER BY expressions. Views
parse `?sort=`/`?dir=` with `parse_sort`; query builders render the ORDER BY
with `order_by`. The dataset page's resource table is the one Python-sorted
table (see `sort_resources`).
"""

import re
from typing import Any


def parse_sort(request, columns, default, default_dir="asc"):
    """?sort=/?dir= validated against `columns`, falling back to the
    defaults. Any dir other than "desc" becomes "asc"."""
    sort = request.GET.get("sort", default)
    sort = sort if sort in columns else default
    dir_ = "desc" if request.GET.get("dir", default_dir) == "desc" else "asc"
    return sort, dir_


def order_by(exprs, sort, dir_, tiebreak):
    """ORDER BY fragment: the column expression, direction, tie-breaker."""
    direction = "DESC" if dir_ == "desc" else "ASC"
    return f"{exprs[sort]} {direction}, {tiebreak}"


# Sortable columns for the resource table on the dataset page — sorted in
# Python by sort_resources, not SQL.
RESOURCE_SORT_COLUMNS = [
    "position",
    "name",
    "format",
    "mimetype",
    "size",
    "last_modified",
]


def _natural_key(value: Any) -> tuple[tuple[int, Any], ...]:
    """Case-insensitive, numeric-aware sort key (ICU-style collation):
    - "Dataset 2" sorts before "Dataset 10" (digit runs compare numerically)
    - "3C Shared Services" sorts before "Aberdeen City Council" (digits
      sort before letters, as in ICU collation)
    - case differences are ignored
    """
    parts = re.split(r"(\d+)", str(value).lower())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p != "")


def _text_key(row: dict[str, Any], key: str, fallback: str | None = None) -> tuple:
    value = row.get(key)
    if value is None and fallback is not None:
        value = row.get(fallback)
    return _natural_key(value or "")


def sort_resources(rows: list[dict[str, Any]], sort: str, dir_: str) -> None:
    """Sort resource rows in place by column key and direction (asc|desc)."""
    reverse = dir_ == "desc"
    if sort == "position":
        # missing position sorts last (after any number)
        rows.sort(
            key=lambda r: r["position"] if isinstance(r.get("position"), int) else float("inf"),
            reverse=reverse,
        )
    elif sort == "size":
        # non-numeric size sorts last (after any number)
        rows.sort(
            key=lambda r: r["size"] if isinstance(r.get("size"), (int, float)) else float("inf"),
            reverse=reverse,
        )
    elif sort == "last_modified":
        # last_modified is often null — fall back to created for sorting
        rows.sort(
            key=lambda r: _text_key(r, "last_modified", fallback="created"),
            reverse=reverse,
        )
    else:
        rows.sort(key=lambda r: _text_key(r, sort), reverse=reverse)
