"""/links/status query layer — statements per (filters, sort, dir),
self-excluding SQL sidebar facet pools and memoised whole-table stats.

The report's statements — the page list/count, the self-excluding sidebar
facet pools and the memoised whole-table stats — all read the
`mv_link_status` matview (ORG_BROKEN_LINKS, the publisher detail count,
stays on the base tables).

`mv_link_status` is the links LEFT JOIN link_check_results LEFT JOIN
datasets LEFT JOIN organisations join, flattened once at build time
(migrations/0003, refreshed by scripts/ingest_ckan.py and
scripts/check_links.py). One row per link occurrence: if N resources point
to the same URL, N rows appear. Harvest state, publisher name and harvest
source title are materialised on the row; the derived `category` is still
computed here (see _CATEGORY_EXPR) so the report's logic stays in one place.
Rows whose package is absent from the datasets snapshot → harvest_state
'unknown'.
"""

import functools

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where

# The report's single relation — the pre-joined matview.
_LINK_ERRORS_FROM = "mv_link_status"

# Publisher display name — materialised in the matview as
# organisations.display_name, falling back to the org slug when the org
# isn't in the registry (e.g. renamed/defunct orgs).
_PUBLISHER_NAME = "publisher_name"

# --- Facet label maps -------------------------------------------------------
# Category derived in SQL from ok / http_status / error prefix.
CATEGORY_LABELS = {
    "OK": "OK",
    "NOT_FOUND": "Not found",
    "GONE": "Gone",
    "OTHER_CLIENT_ERROR": "Client error",
    "SERVER_ERROR": "Server error",
    "DNS_ERROR": "DNS error",
    "TIMEOUT": "Timeout",
    "CONNECTION_ERROR": "Connection error",
    "INVALID_URL": "Invalid URL",
    "NO_URL": "No URL",
    "OTHER_ERROR": "Other error",
}

# Derived category expression — used in SELECT, WHERE and GROUP BY.
# Doubled %% because every statement that carries it is parameterised
# (psycopg3 rule — see queries/core.py).
_CATEGORY_EXPR = (
    "CASE"
    " WHEN ok THEN 'OK'"
    " WHEN http_status = 404 THEN 'NOT_FOUND'"
    " WHEN http_status = 410 THEN 'GONE'"
    " WHEN http_status >= 400 AND http_status < 500 THEN 'OTHER_CLIENT_ERROR'"
    " WHEN http_status >= 500 THEN 'SERVER_ERROR'"
    " WHEN error LIKE 'dns:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%ERR_NAME_NOT_RESOLVED%%') THEN 'DNS_ERROR'"  # noqa: E501
    " WHEN error LIKE 'timeout:%%' OR (error LIKE 'playwright:%%' AND error ILIKE '%%timeout%%') THEN 'TIMEOUT'"
    " WHEN error LIKE 'ssl:%%' OR error LIKE 'connect:%%'"
    "   OR (error LIKE 'playwright:%%' AND (error ILIKE '%%ERR_CERT%%' OR error ILIKE '%%ERR_SSL%%'"
    "   OR error ILIKE '%%ERR_EMPTY_RESPONSE%%' OR error ILIKE '%%ERR_CONNECTION%%'"
    "   OR error ILIKE '%%ERR_HTTP2%%')) THEN 'CONNECTION_ERROR'"
    " WHEN error LIKE 'playwright:%%' AND error ILIKE '%%ERR_TOO_MANY_REDIRECTS%%' THEN 'OTHER_CLIENT_ERROR'"
    " WHEN url IS NULL OR url = '' THEN 'NO_URL'"
    " WHEN error LIKE 'url:%%' THEN 'INVALID_URL'"
    " ELSE 'OTHER_ERROR'"
    " END"
)

# The three harvest states (materialised by the matview): harvested/manual
# come from the datasets snapshot, unknown is the package-absent bucket.
# Rendered via this canonical value→label list.
HARVEST_STATES = [
    ("harvested", "Harvested"),
    ("manual", "Manual"),
    ("unknown", "Unknown"),
]

# Text columns sort case-insensitively. No-response rows (http_status NULL)
# sort below real codes on asc, above them on desc — COALESCE(-1).
LINK_ERRORS_SORT = {
    "url": "LOWER(COALESCE(host, ''))",
    "dataset": "LOWER(COALESCE(dataset_title, ''))",
    # Publisher sorts by the displayed name, not the slug column.
    "publisher": f"LOWER(COALESCE({_PUBLISHER_NAME}, ''))",
    "status": "COALESCE(http_status, -1)",
}

# The order /links/status starts in — shared by parse_sort and preserve_params.
LINK_ERRORS_SORT_DEFAULT = ("url", "asc")


# --- Per-facet clause builders ---------------------------------------------
# Same (filters, exclude) shape as datasets.py; one dict feeds both the
# list/count WHERE and the facet pools (each omits its own group).


def _checked_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    return ["(checked_at IS NOT NULL OR url IS NULL OR url = '')"], []


def _category_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """category WHERE fragment + params, or ([], []) when skipped/inactive."""
    if exclude == "category":
        return [], []
    category = filters.get("category")
    if category:
        return [f"({_CATEGORY_EXPR}) = %s"], [category]
    return [], []


def _status_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """ok/error WHERE fragment."""
    if exclude == "status":
        return [], []
    status = filters.get("status")
    if status == "ok":
        return ["ok = true"], []
    if status == "error":
        return ["ok = false"], []
    return [], []


def _harvested_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """Harvested-state WHERE fragment — harvested/manual/unknown are the
    materialised harvest_state buckets (unknown = package absent)."""
    if exclude == "harvested":
        return [], []
    harvested = filters.get("harvested")
    if harvested == "harvested":
        return ["harvest_state = 'harvested'"], []
    if harvested == "manual":
        return ["harvest_state = 'manual'"], []
    if harvested == "unknown":
        return ["harvest_state = 'unknown'"], []
    return [], []


def _domain_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """domain WHERE fragment + params."""
    if exclude == "domain":
        return [], []
    domain = filters.get("domain")
    if domain == "__none__":
        return ["COALESCE(host, '') = ''"], []
    if domain:
        return ["host = %s"], [domain]
    return [], []


def _publisher_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """Publisher WHERE fragment + params."""
    if exclude == "publisher":
        return [], []
    publisher = filters.get("publisher")
    if publisher:
        return ["org_slug = %s"], [publisher]
    return [], []


_CLAUSES = {
    "_checked": _checked_clause,
    "category": _category_clause,
    "status": _status_clause,
    "domain": _domain_clause,
    "harvested": _harvested_clause,
    "publisher": _publisher_clause,
}


# --- The page list + count -------------------------------------------------


def link_errors_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = facet_where(_CLAUSES, filters)
    order_sql = order_by(LINK_ERRORS_SORT, sort, dir_, "link_id")

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{where}"),
        "list": Query(
            "SELECT url AS resource_url,"
            "  ckan_id, dataset_title AS package_name,"
            "  resource_id, org_slug AS org_name, org_slug,"
            "  http_status AS status,"
            f"  ({_CATEGORY_EXPR}) AS category,"
            "  error AS error_detail,"
            f"  {_PUBLISHER_NAME} AS org_display_name,"
            "  harvest_state,"
            "  harvest_source_title, harvest_source_id,"
            "  ok"
            f" FROM {_LINK_ERRORS_FROM}{where}"
            f" ORDER BY {order_sql}"
            " LIMIT %s OFFSET %s",
        ),
    }


# --- Sidebar facet counts (self-excluding SQL aggregates) ------------------
# Same as /links: each group counts over the pool filtered by the other
# groups, so a selection shrinks sibling counts instead of dead-ending.


def _guarded(fragment: str, guard: str) -> str:
    """WHERE fragment AND-ed with one extra guard clause; with no facet
    fragment this is just " WHERE <guard>"."""
    return f"{fragment} AND {guard}" if fragment else f" WHERE {guard}"


# Guard clauses for the facet pools that group only real values.
_NONEMPTY_ORG = "org_slug <> ''"
_NONEMPTY_DOMAIN = "host IS NOT NULL AND host <> ''"
_NO_DOMAIN = "COALESCE(host, '') = ''"


def _link_errors_facet_counts(filters: dict) -> dict:
    """Compiled facet-count statements for one filter combo."""
    cat_frag, cat_params = facet_where(_CLAUSES, filters, exclude="category")
    status_frag, status_params = facet_where(_CLAUSES, filters, exclude="status")
    domain_frag, domain_params = facet_where(_CLAUSES, filters, exclude="domain")
    harv_frag, harv_params = facet_where(_CLAUSES, filters, exclude="harvested")
    pub_frag, pub_params = facet_where(_CLAUSES, filters, exclude="publisher")

    entry = {
        "params": {
            "categories": cat_params,
            "statuses": status_params,
            "domains": domain_params,
            "no_url": domain_params,
            "harvested": harv_params,
            "publishers": pub_params,
        },
        "categories": Query(
            f"SELECT ({_CATEGORY_EXPR}) AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{cat_frag}"
            f" GROUP BY 1 ORDER BY count DESC, ({_CATEGORY_EXPR})",
        ),
        "statuses": Query(
            "SELECT CASE WHEN COALESCE(ok, false) THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{status_frag}"
            " GROUP BY COALESCE(ok, false) ORDER BY COALESCE(ok, false) DESC",
        ),
        "domains": Query(
            "SELECT host AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(domain_frag, _NONEMPTY_DOMAIN)}"
            " GROUP BY host ORDER BY count DESC, LOWER(host)",
        ),
        "no_url": Query(
            f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{_guarded(domain_frag, _NO_DOMAIN)}",
        ),
        "harvested": Query(
            f"SELECT harvest_state AS value, COUNT(*) AS count FROM {_LINK_ERRORS_FROM}{harv_frag} GROUP BY 1",
        ),
        "publishers": Query(
            f"SELECT org_slug AS value, {_PUBLISHER_NAME} AS name, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(pub_frag, _NONEMPTY_ORG)}"
            " GROUP BY org_slug, publisher_name"
            f" ORDER BY count DESC, LOWER({_PUBLISHER_NAME})",
        ),
    }
    return entry


@cached_unfiltered
def link_errors_facet_counts(filters: dict) -> dict:
    """Sidebar facet counts for /links/status — each group counts over the
    pool filtered by the other groups (self-excluding).

    Returns 'categories', 'statuses', 'no_response', 'domains', 'no_url',
    'harvested' (a state dict) and 'publishers'. Statements run concurrently
    via core.fetch_parallel.

    No-filter calls (used on every request to validate facet values) return
    the memoised pools via core.cached_unfiltered; filtered calls run live.
    """
    entry = _link_errors_facet_counts(filters)
    p = entry["params"]
    # Sequential (not fetch_parallel): the matview is still large enough
    # that concurrent aggregations can spill temp on Railway's Postgres
    # container — see core.fetch_parallel. Each pool is a narrow indexed
    # aggregate, so the sequential cost is small.
    return {
        "categories": entry["categories"].all(*p["categories"]),
        "statuses": entry["statuses"].all(*p["statuses"]),
        "domains": entry["domains"].all(*p["domains"]),
        "no_url": (entry["no_url"].get(*p["no_url"]) or {}).get("n", 0),
        "harvested": {row["value"]: row["count"] for row in entry["harvested"].all(*p["harvested"])},
        "publishers": entry["publishers"].all(*p["publishers"]),
    }


# --- Per-org broken link count (publisher detail page) --------------------

ORG_BROKEN_LINKS = Query(
    "SELECT COUNT(*) AS n"
    " FROM links l"
    " LEFT JOIN link_check_results lcr ON l.url = lcr.url"
    " WHERE l.org_slug = %s"
    " AND (l.url IS NULL OR lcr.ok = false AND lcr.checked_at IS NOT NULL)",
)


# --- Whole-table stats (the report header) --------------------------------

LINK_ERRORS_STATS = Query(
    "SELECT"
    "  COUNT(*) AS total,"
    "  COUNT(*) FILTER (WHERE ok = false OR url IS NULL OR url = '') AS errors,"
    "  COUNT(*) FILTER (WHERE ok) AS resolved"
    f" FROM {_LINK_ERRORS_FROM}"
    " WHERE checked_at IS NOT NULL OR url IS NULL OR url = ''",
)


@functools.cache
def link_errors_stats() -> dict:
    """LINK_ERRORS_STATS row (or {}) — memoised: build-time snapshot."""
    return LINK_ERRORS_STATS.get() or {}
