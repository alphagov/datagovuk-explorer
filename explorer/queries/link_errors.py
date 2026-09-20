"""/links/status query layer — statements per (filters, sort, dir),
self-excluding SQL sidebar facet pools and memoised whole-table stats,
all read from `link_check_results` joined with `links`.

One row per link occurrence: if N resources point to the same URL, N rows
appear. Harvest state, org slug and harvest source title come from the
`datasets` LEFT JOIN on `links.dataset_id`. Rows whose package is absent
from the datasets snapshot join as NULL → harvest_state 'unknown'.
"""

import functools

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# The shared join behind every statement. link_check_results is keyed by
# URL; links provides the per-resource context (dataset, org, host).
# datasets/organisations are LEFT-JOINed for harvest state and display name.
_LINK_ERRORS_FROM = (
    "link_check_results lcr"
    " JOIN links l ON l.id = lcr.link_id"
    " LEFT JOIN datasets d ON d.id = l.dataset_id"
    " LEFT JOIN organisations o ON o.slug = l.org_slug"
)

# Publisher display name — organisations.display_name, falling back to the
# org slug when the org isn't in the registry (e.g. renamed/defunct orgs).
_PUBLISHER_NAME = "COALESCE(NULLIF(o.display_name, ''), l.org_slug)"

# --- Facet label maps -------------------------------------------------------
# Category derived in SQL from lcr.ok / lcr.http_status / lcr.error prefix.
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
_CATEGORY_EXPR = (
    "CASE"
    " WHEN lcr.ok THEN 'OK'"
    " WHEN lcr.http_status = 404 THEN 'NOT_FOUND'"
    " WHEN lcr.http_status = 410 THEN 'GONE'"
    " WHEN lcr.http_status >= 400 AND lcr.http_status < 500 THEN 'OTHER_CLIENT_ERROR'"
    " WHEN lcr.http_status >= 500 THEN 'SERVER_ERROR'"
    " WHEN lcr.error LIKE 'dns:%%' OR (lcr.error LIKE 'playwright:%%' AND lcr.error ILIKE '%%ERR_NAME_NOT_RESOLVED%%') THEN 'DNS_ERROR'"
    " WHEN lcr.error LIKE 'timeout:%%' OR (lcr.error LIKE 'playwright:%%' AND lcr.error ILIKE '%%timeout%%') THEN 'TIMEOUT'"
    " WHEN lcr.error LIKE 'ssl:%%' OR lcr.error LIKE 'connect:%%'"
    "   OR (lcr.error LIKE 'playwright:%%' AND (lcr.error ILIKE '%%ERR_CERT%%' OR lcr.error ILIKE '%%ERR_SSL%%'"
    "   OR lcr.error ILIKE '%%ERR_EMPTY_RESPONSE%%' OR lcr.error ILIKE '%%ERR_CONNECTION%%'"
    "   OR lcr.error ILIKE '%%ERR_HTTP2%%')) THEN 'CONNECTION_ERROR'"
    " WHEN lcr.error LIKE 'playwright:%%' AND lcr.error ILIKE '%%ERR_TOO_MANY_REDIRECTS%%' THEN 'OTHER_CLIENT_ERROR'"
    " WHEN lcr.error = 'url:blank' THEN 'NO_URL'"
    " WHEN lcr.error LIKE 'url:%%' THEN 'INVALID_URL'"
    " ELSE 'OTHER_ERROR'"
    " END"
)

# The three harvest states (see the join above): harvested/manual come from
# the datasets snapshot, unknown is the package-absent bucket. Rendered via
# this canonical value→label list.
HARVEST_STATES = [
    ("harvested", "Harvested"),
    ("manual", "Manual"),
    ("unknown", "Unknown"),
]

# Text columns sort case-insensitively. No-response rows (http_status NULL)
# sort below real codes on asc, above them on desc — COALESCE(-1).
LINK_ERRORS_SORT = {
    "url": "LOWER(COALESCE(l.host, ''))",
    "dataset": "LOWER(COALESCE(l.dataset_title, ''))",
    # Publisher sorts by the displayed name, not the slug column.
    "publisher": f"LOWER(COALESCE({_PUBLISHER_NAME}, ''))",
    "status": "COALESCE(lcr.http_status, -1)",
}

# The order /links/status starts in — shared by parse_sort and preserve_params.
LINK_ERRORS_SORT_DEFAULT = ("url", "asc")


# --- Per-facet clause builders ---------------------------------------------
# Same (filters, exclude) shape as datasets.py; one dict feeds both the
# list/count WHERE and the facet pools (each omits its own group).


def _checked_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    return ["lcr.checked_at IS NOT NULL"], []


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
        return ["lcr.ok = true"], []
    if status == "error":
        return ["lcr.ok = false"], []
    return [], []


def _harvested_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """Harvested-state WHERE fragment — harvested/manual from the datasets
    join, unknown = the package is absent from the snapshot (d.id NULL)."""
    if exclude == "harvested":
        return [], []
    harvested = filters.get("harvested")
    if harvested == "harvested":
        return ["d.harvested = 1"], []
    if harvested == "manual":
        return ["d.harvested = 0"], []
    if harvested == "unknown":
        return ["d.id IS NULL"], []
    return [], []


def _domain_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """domain WHERE fragment + params. l.host is stored on the links row."""
    if exclude == "domain":
        return [], []
    domain = filters.get("domain")
    if domain == "__none__":
        return ["COALESCE(l.host, '') = ''"], []
    if domain:
        return ["l.host = %s"], [domain]
    return [], []


def _publisher_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """Publisher WHERE fragment + params. org_slug is on the links row."""
    if exclude == "publisher":
        return [], []
    publisher = filters.get("publisher")
    if publisher:
        return ["l.org_slug = %s"], [publisher]
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
    order_sql = order_by(LINK_ERRORS_SORT, sort, dir_, "l.id")

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{where}"),
        "list": Query(
            "SELECT l.url AS resource_url,"
            "  l.dataset_id AS package_id, l.dataset_title AS package_name,"
            "  l.resource_id, l.org_slug AS org_name, l.org_slug,"
            "  lcr.http_status AS status,"
            f"  ({_CATEGORY_EXPR}) AS category,"
            "  lcr.error AS error_detail,"
            f"  {_PUBLISHER_NAME} AS org_display_name,"
            "  CASE WHEN d.id IS NULL THEN 'unknown'"
            "       WHEN d.harvested = 1 THEN 'harvested'"
            "       ELSE 'manual' END AS harvest_state,"
            "  d.harvest_source_title, d.harvest_source_id,"
            "  lcr.ok"
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
_NONEMPTY_ORG = "l.org_slug <> ''"
_NONEMPTY_DOMAIN = "l.host IS NOT NULL AND l.host <> ''"
_NO_DOMAIN = "COALESCE(l.host, '') = ''"


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
            "SELECT CASE WHEN lcr.ok THEN 'ok' ELSE 'error' END AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{status_frag}"
            " GROUP BY lcr.ok ORDER BY lcr.ok DESC",
        ),
        "domains": Query(
            "SELECT l.host AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(domain_frag, _NONEMPTY_DOMAIN)}"
            " GROUP BY l.host ORDER BY count DESC, LOWER(l.host)",
        ),
        "no_url": Query(
            f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{_guarded(domain_frag, _NO_DOMAIN)}",
        ),
        "harvested": Query(
            "SELECT CASE WHEN d.id IS NULL THEN 'unknown'"
            "            WHEN d.harvested = 1 THEN 'harvested'"
            "            ELSE 'manual' END AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{harv_frag}"
            " GROUP BY 1",
        ),
        "publishers": Query(
            f"SELECT l.org_slug AS value, {_PUBLISHER_NAME} AS name, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(pub_frag, _NONEMPTY_ORG)}"
            " GROUP BY l.org_slug, o.display_name"
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
    categories, statuses, domains, no_url, harvested, publishers = fetch_parallel(
        [
            lambda: entry["categories"].all(*p["categories"]),
            lambda: entry["statuses"].all(*p["statuses"]),
            lambda: entry["domains"].all(*p["domains"]),
            lambda: (entry["no_url"].get(*p["no_url"]) or {}).get("n", 0),
            lambda: entry["harvested"].all(*p["harvested"]),
            lambda: entry["publishers"].all(*p["publishers"]),
        ],
    )
    return {
        "categories": categories,
        "statuses": statuses,
        "domains": domains,
        "no_url": no_url,
        "harvested": {row["value"]: row["count"] for row in harvested},
        "publishers": publishers,
    }


# --- Per-org broken link count (publisher detail page) --------------------

ORG_BROKEN_LINKS = Query(
    "SELECT COUNT(*) AS n"
    " FROM link_check_results lcr"
    " JOIN links l ON l.id = lcr.link_id"
    " WHERE l.org_slug = %s AND lcr.ok = false AND lcr.checked_at IS NOT NULL",
)


# --- Whole-table stats (the report header) --------------------------------

LINK_ERRORS_STATS = Query(
    "SELECT"
    "  COUNT(*) AS total,"
    "  COUNT(*) FILTER (WHERE NOT lcr.ok) AS errors,"
    "  COUNT(*) FILTER (WHERE lcr.ok) AS resolved"
    " FROM link_check_results lcr"
    " WHERE lcr.checked_at IS NOT NULL",
)


@functools.cache
def link_errors_stats() -> dict:
    """LINK_ERRORS_STATS row (or {}) — memoised: build-time snapshot."""
    return LINK_ERRORS_STATS.get() or {}
