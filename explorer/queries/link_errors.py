"""/links/errors query layer — statements per (filters, sort, dir),
self-excluding SQL sidebar facet pools and memoised whole-table stats,
all read from the `link_errors` table (ingested by
scripts/ingest_link_errors.py).

Harvest state, org slug and harvest source title are not stored on
link_errors rows: every statement LEFT
JOINs `datasets` on package_id, so the join shape is defined once here.
Rows whose package is absent from the datasets snapshot join as NULL →
harvest_state 'unknown'. The domain facet's value is derived too — the
ingest CSV stores only resource_url, so _URL_HOST pulls the host out in
SQL (one shared expression for the sort, the facet pool and its clause).
"""

import functools

from explorer.sort import order_by

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# The shared join behind every statement. link_errors is ingested against
# whatever datasets snapshot exists, so datasets-owned columns (harvest
# state, org display name) come from this join rather than being stored.
# The organisations join maps e.org_name (the CKAN slug) to its display
# name; it's 0-or-1 rows per error row, so it never multiplies counts.
_LINK_ERRORS_FROM = (
    "link_errors e LEFT JOIN datasets d ON d.id = e.package_id LEFT JOIN organisations o ON o.slug = e.org_name"
)

# Publisher display name — organisations.display_name, falling back to the
# org slug when the org isn't in the registry (e.g. renamed/defunct orgs).
_PUBLISHER_NAME = "COALESCE(NULLIF(o.display_name, ''), e.org_name)"

# --- Facet label maps ------------------------------------------------------
# Raw category codes from the checker -> display labels (the harvesters'
# TYPE_LABELS pattern). Rows/facets/pills all render through these so they
# can't drift.

CATEGORY_LABELS = {
    "OK": "OK",
    "NOT_FOUND": "Not found",
    "GONE": "Gone",
    "OTHER_CLIENT_ERROR": "Client error",
    "SERVER_ERROR": "Server error",
    "DNS_ERROR": "DNS error",
    "TIMEOUT": "Timeout",
    "CONNECTION_ERROR": "Connection error",
    "CONNECTION_REFUSED": "Connection refused",
    "OTHER_ERROR": "Other error",
}

# The three harvest states (see the join above): harvested/manual come from
# the datasets snapshot, unknown is the package-absent bucket. Rendered via
# this canonical value→label list.
HARVEST_STATES = [
    ("harvested", "Harvested"),
    ("manual", "Manual"),
    ("unknown", "Unknown"),
]

# The two to-delete states — the checker's remove-this-dead-link
# recommendation behind the To delete column.
TO_DELETE_VALUES = [
    ("yes", "Yes"),
    ("no", "No"),
]

# Host from resource_url — pulls "host[:port]" out of "scheme://host:port/
# path" and drops any :port.
_URL_HOST = "split_part(substring(e.resource_url FROM '://([^/]+)'), ':', 1)"

# Text columns sort case-insensitively. No-response rows (http_status NULL)
# sort below real codes on asc, above them on desc — COALESCE(-1).
LINK_ERRORS_SORT = {
    "url": f"LOWER(COALESCE({_URL_HOST}, ''))",
    "dataset": "LOWER(COALESCE(e.package_name, ''))",
    # Publisher sorts by the displayed name, not the slug column.
    "publisher": f"LOWER(COALESCE({_PUBLISHER_NAME}, ''))",
    "status": "COALESCE(e.http_status, -1)",
    "to_delete": "e.to_delete",
}


# --- Per-facet clause builders ---------------------------------------------
# Same (filters, exclude) shape as datasets.py; one dict feeds both the
# list/count WHERE and the facet pools (each omits its own group).


def _category_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """category WHERE fragment + params, or ([], []) when skipped/inactive."""
    if exclude == "category":
        return [], []
    category = filters.get("category")
    if category:
        return ["e.category = %s"], [category]
    return [], []


def _status_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """http-status WHERE fragment + params. `__none__` is the no-response
    selection (DNS/timeout rows that never got an HTTP code)."""
    if exclude == "status":
        return [], []
    status = filters.get("status")
    if status == "__none__":
        return ["e.http_status IS NULL"], []
    if status:
        return ["e.http_status = %s"], [int(status)]
    return [], []


def _to_delete_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """to-delete WHERE fragment — yes = the checker recommends removing
    the dead link from the catalogue."""
    if exclude == "to_delete":
        return [], []
    to_delete = filters.get("to_delete")
    if to_delete == "yes":
        return ["e.to_delete = true"], []
    if to_delete == "no":
        return ["e.to_delete = false"], []
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
    """domain WHERE fragment + params. The host isn't stored — _URL_HOST
    derives it from resource_url in SQL, so filter/facet/sort share the one
    expression. __none__ is the no-host selection (scheme-less URLs)."""
    if exclude == "domain":
        return [], []
    domain = filters.get("domain")
    if domain == "__none__":
        return [f"COALESCE({_URL_HOST}, '') = ''"], []
    if domain:
        return [f"{_URL_HOST} = %s"], [domain]
    return [], []


def _publisher_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """Publisher (org-name) WHERE fragment + params. org_name rides on the
    error row itself (from the checker), not the datasets join."""
    if exclude == "publisher":
        return [], []
    publisher = filters.get("publisher")
    if publisher:
        return ["e.org_name = %s"], [publisher]
    return [], []


_CLAUSES = {
    "category": _category_clause,
    "status": _status_clause,
    "to_delete": _to_delete_clause,
    "domain": _domain_clause,
    "harvested": _harvested_clause,
    "publisher": _publisher_clause,
}


# --- The page list + count -------------------------------------------------


def link_errors_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = facet_where(_CLAUSES, filters)
    order_sql = order_by(LINK_ERRORS_SORT, sort, dir_, "e.id")

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{where}"),
        "list": Query(
            "SELECT e.id, e.package_id, e.package_name, e.resource_id,"
            "  e.resource_url, e.datagovuk_url, e.org_name, e.org_id,"
            "  e.http_status AS status, e.category, e.error_detail,"
            "  e.to_delete,"
            "  d.org_slug,"
            f"  {_PUBLISHER_NAME} AS org_display_name,"
            "  CASE WHEN d.id IS NULL THEN 'unknown'"
            "       WHEN d.harvested = 1 THEN 'harvested'"
            "       ELSE 'manual' END AS harvest_state,"
            "  d.harvest_source_title, d.harvest_source_id"
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


# Guard clauses for the facet pools that group only real values (blank
# categories / org names / scheme-less URLs never appear as facet items).
_NONEMPTY_CATEGORY = "e.category <> ''"
_NONEMPTY_ORG = "e.org_name <> ''"
_NONEMPTY_DOMAIN = f"COALESCE({_URL_HOST}, '') <> ''"
_NO_DOMAIN = f"COALESCE({_URL_HOST}, '') = ''"


def _link_errors_facet_counts(filters: dict) -> dict:
    """Compiled facet-count statements for one (category/status/to_delete/
    domain/harvested/publisher) combo — the eight Queries plus per-statement
    params."""
    cat_frag, cat_params = facet_where(_CLAUSES, filters, exclude="category")
    status_frag, status_params = facet_where(_CLAUSES, filters, exclude="status")
    td_frag, td_params = facet_where(_CLAUSES, filters, exclude="to_delete")
    domain_frag, domain_params = facet_where(_CLAUSES, filters, exclude="domain")
    harv_frag, harv_params = facet_where(_CLAUSES, filters, exclude="harvested")
    pub_frag, pub_params = facet_where(_CLAUSES, filters, exclude="publisher")

    entry = {
        "params": {
            "categories": cat_params,
            "statuses": status_params,
            "no_response": status_params,
            "to_delete": td_params,
            "domains": domain_params,
            "no_url": domain_params,
            "harvested": harv_params,
            "publishers": pub_params,
        },
        "categories": Query(
            "SELECT e.category AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(cat_frag, _NONEMPTY_CATEGORY)}"
            " GROUP BY e.category ORDER BY count DESC, e.category",
        ),
        # Real HTTP codes only — the no-response rows (NULL status) trail
        # as their own bucket (the /links "No URL" pattern).
        "statuses": Query(
            "SELECT e.http_status::text AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(status_frag, 'e.http_status IS NOT NULL')}"
            " GROUP BY e.http_status ORDER BY count DESC, e.http_status",
        ),
        "no_response": Query(
            f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{_guarded(status_frag, 'e.http_status IS NULL')}",
        ),
        # Every host in the pool (the view collapses the list behind its
        # More toggle); scheme-less/malformed URLs trail as the No URL
        # bucket. LOWER(...) is repeated in ORDER BY because Postgres can't
        # resolve a bare alias inside LOWER.
        "domains": Query(
            f"SELECT {_URL_HOST} AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(domain_frag, _NONEMPTY_DOMAIN)}"
            f" GROUP BY 1 ORDER BY count DESC, LOWER({_URL_HOST})",
        ),
        "no_url": Query(
            f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{_guarded(domain_frag, _NO_DOMAIN)}",
        ),
        "to_delete": Query(
            "SELECT CASE WHEN e.to_delete THEN 'yes' ELSE 'no' END AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{td_frag}"
            " GROUP BY e.to_delete",
        ),
        "harvested": Query(
            "SELECT CASE WHEN d.id IS NULL THEN 'unknown'"
            "            WHEN d.harvested = 1 THEN 'harvested'"
            "            ELSE 'manual' END AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{harv_frag}"
            " GROUP BY 1",
        ),
        # Every publisher in the pool is a facet (the view collapses the
        # list behind a "More publishers" toggle). value = org name, name =
        # display name.
        "publishers": Query(
            f"SELECT e.org_name AS value, {_PUBLISHER_NAME} AS name, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(pub_frag, _NONEMPTY_ORG)}"
            " GROUP BY e.org_name, o.display_name"
            f" ORDER BY count DESC, LOWER({_PUBLISHER_NAME})",
        ),
    }
    return entry


@cached_unfiltered
def link_errors_facet_counts(filters: dict) -> dict:
    """Sidebar facet counts for /links/errors — each group counts over the
    pool filtered by the other groups (self-excluding).

    Returns 'categories', 'statuses', 'no_response', 'domains', 'no_url',
    'to_delete' (a yes/no dict), 'harvested' (a state dict) and
    'publishers' — shapes as described by the queries above. The eight
    statements run concurrently via core.fetch_parallel.

    No-filter calls (used on every request to validate facet values) return
    the memoised pools via core.cached_unfiltered; filtered calls run live.
    """
    entry = _link_errors_facet_counts(filters)
    p = entry["params"]
    categories, statuses, no_resp, to_delete, domains, no_url, harvested, publishers = fetch_parallel(
        [
            lambda: entry["categories"].all(*p["categories"]),
            lambda: entry["statuses"].all(*p["statuses"]),
            lambda: (entry["no_response"].get(*p["no_response"]) or {}).get("n", 0),
            lambda: entry["to_delete"].all(*p["to_delete"]),
            lambda: entry["domains"].all(*p["domains"]),
            lambda: (entry["no_url"].get(*p["no_url"]) or {}).get("n", 0),
            lambda: entry["harvested"].all(*p["harvested"]),
            lambda: entry["publishers"].all(*p["publishers"]),
        ],
    )
    return {
        "categories": categories,
        "statuses": statuses,
        "no_response": no_resp,
        "to_delete": {row["value"]: row["count"] for row in to_delete},
        "domains": domains,
        "no_url": no_url,
        "harvested": {row["value"]: row["count"] for row in harvested},
        "publishers": publishers,
    }


# --- Whole-table stats (the report header) --------------------------------

# Page-header stats: current failures (every category but OK) vs resolved
# (OK = previously broken, now working).
LINK_ERRORS_STATS = Query(
    """SELECT
         COUNT(*) AS total,
         COUNT(*) FILTER (WHERE COALESCE(category, '') <> 'OK') AS errors,
         COUNT(*) FILTER (WHERE category = 'OK') AS resolved
       FROM link_errors""",
)


@functools.cache
def link_errors_stats() -> dict:
    """LINK_ERRORS_STATS row (or {}) — memoised: build-time snapshot."""
    return LINK_ERRORS_STATS.get() or {}
