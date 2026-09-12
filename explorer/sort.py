"""Client-visible sort-column whitelists, plus the one in-place sorter.

Every page whitelists the keys it accepts in ?sort=; unknown keys fall back
to the page's default. Sorting itself happens in PostgreSQL (ORDER BY in
the query builders — datasets, org, harvester, series, ...) except the
dataset page's resource table, which is sorted in place by sort_resources.

Text columns sort case-insensitively and numeric-aware (locale-aware
collation: "base" sensitivity, numeric ordering).
"""

import re
from typing import Any

# Sortable columns for the org table on the /organisations page (the
# accepted-keys whitelist — sorting happens in PostgreSQL, see
# ORG_SORT_EXPRS in explorer/queries/organisations.py)
SORT_COLUMNS = [
    "name",
    "dataset_count",
    "resource_count",
    "views",
    "type",
    "state",
    "approval_status",
    "created",
    "last_published",
]

# Sortable columns for the harvest sources table on the /harvesters page
HARVESTER_SORT_COLUMNS = [
    "title",
    "org_name",
    "type",
    "active",
    "frequency",
    "dataset_count",
    "last_run",
]

# Sortable columns for the dataset table on the organisation page
DATASET_SORT_COLUMNS = [
    "title",
    "metadata_created",
    "metadata_modified",
    "resources",
    "views",
    "harvested",
]

# Sortable columns for the all-datasets table on the /datasets page — sorting
# happens in PostgreSQL (ORDER BY in the /datasets query builder,
# explorer/queries/datasets.py); this list is just the accepted-keys whitelist.
DATASETS_SORT_COLUMNS = [
    "title",
    "organisation",
    "metadata_created",
    "metadata_modified",
    "resources",
    "views",
    "harvested",
]

# Sortable columns for the resource table on the dataset page
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
