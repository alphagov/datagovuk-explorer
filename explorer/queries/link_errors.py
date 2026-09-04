"""/links/errors query layer — statements built per (filters, sort, dir),
self-excluding SQL sidebar facet pools and the memoised whole-table stats,
all read from the `link_errors` table (ingested by
scripts/ingest_link_errors.py from data/errors-current.csv).

Harvested / harvest source are DERIVED, not stored (docs/link-errors-report
.md §3): every statement LEFT JOINs `datasets` on package_id, so the
join shape — org slug, harvested state and harvest source title — is
defined once here. Rows whose package is absent from the datasets snapshot
(~3.6%) have d.id NULL → harvest_state 'unknown'. The domain facet's host
is derived too — the ingest CSV stores only resource_url, so _URL_HOST
pulls the host out in SQL (one shared expression for the sort, the facet
pool and its WHERE clause).

filters: { category: code | None, status: "404" | "__none__" | None,
           to_delete: "yes" | "no" | None, host: name | "__none__" | None,
           harvested: harvested|manual|unknown | None, publisher: org | None }.
"""

import functools

from .core import Query, cached_unfiltered, facet_where, fetch_parallel

# The one shared join. The /links page's links table is written by build_db
# in the same atomic run as datasets, so it denormalises display columns;
# link_errors is ingested separately (like reviews) and may run against an
# older datasets snapshot, so the report derives the datasets-owned columns
# from this join instead of duplicating them (docs/link-errors-report.md §3).
# The organisations join resolves publisher display names: e.org_name holds
# the CKAN org slug, and organisations is the slug → display_name registry
# (930 of 931 error orgs; the datasets snapshot alone would miss 5). It's
# 0-or-1 rows per error row, so it never multiplies counts.
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

# The three harvest states (see the LEFT JOIN above): harvested/manual come
# from the datasets snapshot, unknown is the package-absent bucket. The
# canonical value→label list for the pills/badges — the sidebar facet list
# sorts by its pool's count order in the view, not by this order.
HARVEST_STATES = [
    ("harvested", "Harvested"),
    ("manual", "Manual"),
    ("unknown", "Unknown"),
]

# The two to-delete states — the checker's remove-this-dead-link
# recommendation behind the To delete column (true on ~45k rows). Canonical
# value→label list for the pills/badges — the sidebar facet list sorts by
# its pool's count order in the view, not by this order.
TO_DELETE_VALUES = [
    ("yes", "Yes"),
    ("no", "No"),
]

# Sortable column key -> SQL ORDER BY expression (already LOWER()/COALESCE'd,
# so the builder only appends ASC/DESC). Text columns sort case-insensitively.
LINK_ERRORS_SORT_COLUMNS = ["url", "dataset", "publisher", "status", "checked", "to_delete"]

# The checked URL's host — substring's capture group pulls "host[:port]" out
# of "scheme://host:port/path" (no match -> NULL -> COALESCE'd to ''), then
# split_part drops any :port. Only used for the url sort, so the regex runs
# per ORDER BY pass over the filtered pool (89k rows worst case — fine).
_URL_HOST = "split_part(substring(e.resource_url FROM '://([^/]+)'), ':', 1)"

LINK_ERRORS_SORT_EXPRS = {
    "url": f"LOWER(COALESCE({_URL_HOST}, ''))",
    "dataset": "LOWER(COALESCE(e.package_name, ''))",
    # Publisher sorts by display name (same value the cell shows), not the
    # slug column — o rides the shared organisations join.
    "publisher": f"LOWER(COALESCE({_PUBLISHER_NAME}, ''))",
    # No-response rows (http_status NULL) sort below real codes on asc,
    # above them on desc — COALESCE(-1), the reviews scores pattern.
    "status": "COALESCE(e.http_status, -1)",
    # ISO timestamps sort chronologically as text (same format across runs)
    "checked": "e.checked_at",
    "to_delete": "e.to_delete",
}


# --- Per-facet clause builders ---------------------------------------------
# The shared (filters, exclude) -> ([clause, ...], [param, ...]) shape from
# datasets.py/links.py. One builder dict, two consumers: link_errors_stmts
# ANDs everything for the list/count WHERE, and each facet pool omits its
# own group via core.facet_where. d.* columns are only in WHERE clauses when
# the LEFT JOIN matches — harvested/manual/unknown map to that join.


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


def _host_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """Derived-host WHERE fragment + params. The host is NOT stored (the
    ingest CSV has no host column): _URL_HOST pulls it out of resource_url
    in SQL, so filter/facet/sort all share the one expression — same
    derived-not-stored principle as the harvest states above. __none__ is
    the no-host selection (scheme-less / malformed URLs)."""
    if exclude == "host":
        return [], []
    host = filters.get("host")
    if host == "__none__":
        return [f"COALESCE({_URL_HOST}, '') = ''"], []
    if host:
        return [f"{_URL_HOST} = %s"], [host]
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
    "host": _host_clause,
    "harvested": _harvested_clause,
    "publisher": _publisher_clause,
}


# --- The page list + count -------------------------------------------------


def link_errors_stmts(filters: dict, sort: str, dir_: str) -> dict:
    """Return { count, list, params } for one (filters, sort, dir) combo."""
    where, params = facet_where(_CLAUSES, filters)
    order_sql = f"{LINK_ERRORS_SORT_EXPRS[sort]} {'DESC' if dir_ == 'desc' else 'ASC'}"
    # `, e.id` pins tied rows to ingest order — an unpinned ORDER BY would
    # reshuffle pages (89k rows, ~45k share each checked_at value).
    order_sql += ", e.id"

    return {
        "params": params,
        "count": Query(f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{where}"),
        "list": Query(
            "SELECT e.id, e.package_id, e.package_name, e.resource_id,"
            "  e.resource_url, e.datagovuk_url, e.org_name, e.org_id,"
            "  e.http_status AS status, e.category, e.error_detail,"
            "  e.to_delete, e.checked_at,"
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
# Same machinery as /links: each group counts over the pool filtered by the
# *other* groups (excluding its own), so a selection shrinks the sibling
# counts instead of dead-ending into 0 results. All pools share the LEFT
# JOIN, so the harvested pool and the whole-dataset aggregate scan the same
# two indexed tables.


def _guarded(fragment: str, guard: str) -> str:
    """WHERE fragment plus one extra guard clause (e.g. `e.http_status IS
    NOT NULL`), AND-ed onto any facet fragment — "" when there's no
    fragment means a bare " WHERE <guard>", mirroring links.py."""
    return f"{fragment} AND {guard}" if fragment else f" WHERE {guard}"


# Guard clauses for the facet pools that group only real values (blank
# categories / org names / scheme-less URLs never appear as facet items).
_NONEMPTY_CATEGORY = "e.category <> ''"
_NONEMPTY_ORG = "e.org_name <> ''"
_NONEMPTY_HOST = f"COALESCE({_URL_HOST}, '') <> ''"
_NO_HOST = f"COALESCE({_URL_HOST}, '') = ''"


def _link_errors_facet_counts(filters: dict) -> dict:
    """Compiled facet-count statements for one (category/status/to_delete/
    host/harvested/publisher) combo — the eight Queries plus per-statement
    params."""
    cat_frag, cat_params = facet_where(_CLAUSES, filters, exclude="category")
    status_frag, status_params = facet_where(_CLAUSES, filters, exclude="status")
    td_frag, td_params = facet_where(_CLAUSES, filters, exclude="to_delete")
    host_frag, host_params = facet_where(_CLAUSES, filters, exclude="host")
    harv_frag, harv_params = facet_where(_CLAUSES, filters, exclude="harvested")
    pub_frag, pub_params = facet_where(_CLAUSES, filters, exclude="publisher")

    entry = {
        "params": {
            "categories": cat_params,
            "statuses": status_params,
            "no_response": status_params,
            "to_delete": td_params,
            "hosts": host_params,
            "no_url": host_params,
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
        # Derived hosts — every host in the pool (no cap, the view's More
        # toggle cuts the list); the scheme-less/malformed URL rows trail as
        # the No URL bucket. GROUP BY 1 + a repeated LOWER(expression) order
        # (Postgres won't resolve a bare alias inside LOWER).
        "hosts": Query(
            f"SELECT {_URL_HOST} AS value, COUNT(*) AS count"
            f" FROM {_LINK_ERRORS_FROM}{_guarded(host_frag, _NONEMPTY_HOST)}"
            f" GROUP BY 1 ORDER BY count DESC, LOWER({_URL_HOST})",
        ),
        "no_url": Query(
            f"SELECT COUNT(*) AS n FROM {_LINK_ERRORS_FROM}{_guarded(host_frag, _NO_HOST)}",
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
        # No cap — the sidebar renders every publisher in the pool; the view
        # cuts the long list behind its "More publishers" toggle (all 931
        # orgs are facets, not just the biggest error producers). value is
        # the org slug (the facet URL/filter key); name is the display name.
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
    pool filtered by the other groups (self-excluding). Returns:

      'categories':  [{'value': category-code, 'count': n}, ...] count desc
      'statuses':    [{'value': "404", 'count': n}, ...] count desc
      'no_response': int — rows with no HTTP status (the trailing bucket)
      'hosts':       [{'value': host, 'count': n}, ...] all hosts, count
                     desc (no cap — the view's More toggle cuts the list)
      'no_url':      int — rows whose URL has no parseable host (the
                     trailing bucket)
      'to_delete':   {'yes': n, 'no': n}
      'harvested':   {'harvested': n, 'manual': n, 'unknown': n}
      'publishers':  [{'value': org-slug, 'name': display-name,
                     'count': n}, ...] all orgs, count desc (no cap — the
                     view's More toggle cuts the rendered list; name falls
                     back to the slug for orgs missing from organisations)

    The eight statements are eight independent single-SELECT aggregates, so
    they run concurrently via core.fetch_parallel. No-filter calls return
    the memoised pools via core.cached_unfiltered — every /links/errors
    request calls the unfiltered version for its category/status/host/
    publisher validation whitelists; filtered calls run live.
    """
    entry = _link_errors_facet_counts(filters)
    p = entry["params"]
    categories, statuses, no_resp, to_delete, hosts, no_url, harvested, publishers = fetch_parallel(
        [
            lambda: entry["categories"].all(*p["categories"]),
            lambda: entry["statuses"].all(*p["statuses"]),
            lambda: (entry["no_response"].get(*p["no_response"]) or {}).get("n", 0),
            lambda: entry["to_delete"].all(*p["to_delete"]),
            lambda: entry["hosts"].all(*p["hosts"]),
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
        "hosts": hosts,
        "no_url": no_url,
        "harvested": {row["value"]: row["count"] for row in harvested},
        "publishers": publishers,
    }


# --- Whole-table stats (the report header) --------------------------------

# Aggregate link-error stats for the page header — rows that currently fail
# (every category but OK) vs the resolved population (OK = previously
# broken, now working). Memoised: build-time snapshot.
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
