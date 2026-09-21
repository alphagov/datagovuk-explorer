"""Data-quality report definitions (REPORTS) and their compiled
count/list statements."""

import functools

from explorer.sort import order_by as _order_by_sql

from .core import Query, facet_where

# --- Data-quality report definitions and their compiled count/list statements ---
# Each report is a count + paginated list query. `kind` tells the template
# which column set to render (orgs / datasets / links).
#
# Regular reports differ only in their WHERE clause: `_dataset_report_sql` /
# `_link_report_sql` build both statements from that one clause, so count
# and list can't drift. The special reports (duplicate-urls, duplicate-content)
# keep hand-written SQL.
#
# There's deliberately no plain "duplicate titles" report: an exact title
# match with different content is either a genuine duplicate (caught by
# datasets-duplicate-content, which hashes title+notes+resource URLs) or a
# dated/renamed series (caught by build_series.py) — a title-only report
# would just re-surface both of those with less precision.
#
# Each report's SQL carries a {key} placeholder per facet, replaced by the
# facet's filter_sql when a value is selected, or '' when not.

# --- Shared column lists / orderings for the regular reports ---
DATASET_REPORT_COLS = "id, title, name, org_slug, org_display_name, metadata_created, metadata_modified, views, notes"
DATASET_REPORT_ORDER = "LOWER(org_display_name), LOWER(title), id"
LINK_REPORT_COLS = (
    "id, dataset_id, org_slug, org_display_name, dataset_title, name, description, url, host, format_norm AS format"
)
LINK_REPORT_ORDER = "LOWER(org_display_name), LOWER(dataset_title), id"

DATASET_REPORT_SORT = {
    "org": "LOWER(org_display_name)",
    "title": "LOWER(COALESCE(title, ''))",
    "metadata_created": "COALESCE(metadata_created, '')",
    "metadata_modified": "COALESCE(metadata_modified, '')",
    "views": "COALESCE(views, 0)",
}
DATASET_REPORT_SORT_DEFAULT = ("org", "asc")

LINK_REPORT_SORT = {
    "org": "LOWER(org_display_name)",
    "dataset_title": "LOWER(COALESCE(dataset_title, ''))",
    "name": "LOWER(COALESCE(name, ''))",
    "url": "LOWER(COALESCE(url, ''))",
    "format": "LOWER(COALESCE(format_norm, ''))",
}
LINK_REPORT_SORT_DEFAULT = ("org", "asc")

DUPLICATE_CONTENT_SORT = {
    "dataset_count": "dataset_count",
    "org_count": "org_count",
    "title": "LOWER(title)",
}
DUPLICATE_CONTENT_SORT_DEFAULT = ("dataset_count", "desc")

DUPLICATE_URL_SORT = {
    "dataset_count": "dataset_count",
    "org_count": "org_count",
    "url": "LOWER(url)",
}
DUPLICATE_URL_SORT_DEFAULT = ("dataset_count", "desc")

SUSPICIOUS_REDIRECT_SORT = {
    "link_count": "link_count",
    "org_count": "org_count",
    "final_url": "LOWER(final_url)",
}
SUSPICIOUS_REDIRECT_SORT_DEFAULT = ("link_count", "desc")

# Prefixed variants for the special reports' aliased queries (d./datasets./
# l. table aliases — the bare column names would be ambiguous with their
# joins).
_DATASET_REPORT_COLS_D = ", ".join(f"d.{c}" for c in DATASET_REPORT_COLS.split(", "))
_LINK_REPORT_COLS_L = ", ".join(f"l.{c}" for c in LINK_REPORT_COLS.split(", "))


def _dataset_report_sql(where: str) -> dict:
    """Count + list statements for a regular datasets report — one WHERE."""
    return {
        "where": where,
        "count_sql": f"SELECT COUNT(*) AS n FROM datasets WHERE {where}",
        "list_sql": (
            f"SELECT {DATASET_REPORT_COLS} FROM datasets WHERE {where} ORDER BY {{order_by}} LIMIT %s OFFSET %s"
        ),
    }


def _link_report_sql(where: str) -> dict:
    """Count + list statements for a regular links report — one WHERE."""
    return {
        "where": where,
        "count_sql": f"SELECT COUNT(*) AS n FROM links WHERE {where}",
        "list_sql": (f"SELECT {LINK_REPORT_COLS} FROM links WHERE {where} ORDER BY {{order_by}} LIMIT %s OFFSET %s"),
    }


# The URL filter shared by links-duplicate-urls' count + list statements.
_DUP_URLS_FILTER = "url IS NOT NULL AND url != ''"

# Shared per-facet clause builders for the reports' sidebar facet counts —
# same (filters, exclude) shape as datasets.py, fed to core.facet_where.


def _report_org_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """org facet WHERE fragment — org_slug equality on the outer table."""
    if exclude == "org":
        return [], []
    slug = filters.get("org")
    if slug:
        return ["org_slug = %s"], [slug]
    return [], []


_REPORT_FACET_CLAUSES = {
    "org": _report_org_clause,
}

REPORTS = [
    {
        "key": "datasets-no-description",
        "label": "Datasets with no description",
        "description": "",
        "kind": "datasets",
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM datasets
            WHERE (notes IS NULL OR TRIM(notes) = ''){facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        **_dataset_report_sql("(notes IS NULL OR TRIM(notes) = ''){org}"),
    },
    {
        "key": "datasets-short-description",
        "label": "Datasets with a short description",
        "description": ("Datasets with a description under 80 characters"),
        "kind": "datasets",
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM datasets
            WHERE notes IS NOT NULL AND TRIM(notes) != '' AND LENGTH(TRIM(notes)) < 80{facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        **_dataset_report_sql(
            "notes IS NOT NULL AND TRIM(notes) != '' AND LENGTH(TRIM(notes)) < 80{org}",
        ),
    },
    {
        "key": "datasets-short-title",
        "label": "Datasets with a short title",
        "description": ("Datasets with a title under 20 characters"),
        "kind": "datasets",
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM datasets
            WHERE title IS NOT NULL AND TRIM(title) != '' AND LENGTH(TRIM(title)) < 20{facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        **_dataset_report_sql(
            "title IS NOT NULL AND TRIM(title) != '' AND LENGTH(TRIM(title)) < 20{org}",
        ),
    },
    {
        "key": "datasets-withdrawn",
        "label": "Datasets that have been withdrawn",
        "description": ("Datasets marked as withdrawn, retired or no longer available in their title or description."),
        "kind": "datasets",
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM datasets
            WHERE (title LIKE '%%withdrawn%%'
              OR notes LIKE '%%dataset has been withdrawn%%'
              OR notes LIKE '%%no longer updated and has been retired%%'
              OR notes LIKE '%%record has been retired%%'
              OR notes LIKE '%%dataset has been retired%%'){facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        # The LIKE patterns are doubled (%%…%%) — see the psycopg3 binding
        # rule in queries/core.py. The OR conditions are wrapped in parens so
        # {org} appends as AND org_slug = %s with correct precedence.
        **_dataset_report_sql(
            "(title LIKE '%%withdrawn%%'"
            " OR notes LIKE '%%dataset has been withdrawn%%'"
            " OR notes LIKE '%%no longer updated and has been retired%%'"
            " OR notes LIKE '%%record has been retired%%'"
            " OR notes LIKE '%%dataset has been retired%%'){org}",
        ),
    },
    {
        "key": "datasets-duplicate-content",
        "label": "Datasets with duplicate content",
        # The card counts redundant records, not datasets-with-a-duplicate
        # (12,707 vs 10,859), so it gets its own label.
        "dashboard_label": "Duplicate datasets",
        # kind is "duplicate-content" (no such totals bucket), but the card's
        # count is still a share of all datasets — name the bucket explicitly.
        "percent_of": "datasets",
        "description": ("Datasets that share an identical title, description and link URLs "),
        "kind": "duplicate-content",
        # content_hash (dataset_content_hash, built by scripts/build_db.py) is
        # an md5 of the normalised title+notes+resource-URL-set — an exact
        # match means byte-for-byte duplicate content, no self-join needed.
        #
        # count_sql/list_sql paginate by *group* (one row per duplicated
        # hash) — the report page's own count must match those rows 1:1
        # (test_every_report_count_matches_list).
        #
        # dashboard_count_sql is the dashboard card's number instead: how
        # many *redundant* records exist — every member of a duplicate group
        # except the one copy you'd keep, i.e. sum(size - 1) over groups.
        # (Counting all members would instead answer "how many datasets have
        # a duplicate", which is the less actionable number.) As of the last
        # full build: 1,848 groups covering 12,707 records, of which 10,859
        # are redundant. Note the sum must be over *groups* — summing
        # (c - 1) over rows of a window-function count would be n(n-1).
        #
        # Publisher facet (?org=<slug>): a group can span more than one
        # organisation (that's the interesting case — the same content
        # published twice under different publishers), so filtering by org
        # narrows to groups with a member in that org, not to that org's
        # rows within the group — dataset_count/org_count stay whole-group
        # totals. The {org} placeholder sits in HAVING (content_hash is the
        # GROUP BY key, so a bare reference there is valid SQL) rather than
        # WHERE, so it can't shrink a group's own aggregate before HAVING
        # COUNT(*) > 1 sees it.
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT d.org_slug AS slug, d.org_display_name AS name,
                     COUNT(DISTINCT h.content_hash) AS count
            FROM dataset_content_hash h
            JOIN datasets d ON d.id = h.dataset_id
            WHERE h.content_hash IN (
                SELECT content_hash FROM dataset_content_hash GROUP BY content_hash HAVING COUNT(*) > 1
            ){facet_and}
            GROUP BY d.org_slug, d.org_display_name
            ORDER BY count DESC, LOWER(d.org_display_name)""",
                "filter_sql": (
                    " AND content_hash IN ("
                    "SELECT hh.content_hash FROM dataset_content_hash hh "
                    "JOIN datasets dd ON dd.id = hh.dataset_id WHERE dd.org_slug = %s)"
                ),
            },
        ],
        "count_sql": """SELECT COUNT(*) AS n FROM (
               SELECT content_hash FROM dataset_content_hash
               GROUP BY content_hash
               HAVING COUNT(*) > 1{org}
             ) sub""",
        "dashboard_count_sql": """SELECT COALESCE(SUM(n - 1), 0) AS n FROM (
               SELECT COUNT(*) AS n FROM dataset_content_hash
               GROUP BY content_hash
               HAVING COUNT(*) > 1
             ) sub""",
        # List: one row per duplicate-content group — a representative title
        # (every member's title is identical by construction) with the
        # dataset/org counts, sorted by most-duplicated.
        "list_sql": """SELECT h.content_hash, MIN(d.title) AS title,
                     COUNT(*) AS dataset_count, COUNT(DISTINCT d.org_slug) AS org_count
              FROM dataset_content_hash h
              JOIN datasets d ON d.id = h.dataset_id
              GROUP BY h.content_hash
              HAVING COUNT(*) > 1{org}
              ORDER BY {order_by}
              LIMIT %s OFFSET %s""",
        # Detail: every dataset in one content-hash group (used when ?hash= is set)
        "detail_sql": f"""SELECT {_DATASET_REPORT_COLS_D}
                FROM dataset_content_hash h
                JOIN datasets d ON d.id = h.dataset_id
                WHERE h.content_hash = %s
                ORDER BY {{order_by}}
                LIMIT %s OFFSET %s""",
        "detail_count_sql": "SELECT COUNT(*) AS n FROM dataset_content_hash WHERE content_hash = %s",
    },
    {
        "key": "links-no-name",
        "label": "Links with no name",
        "description": "",
        "kind": "links",
        "hidden_cols": ["name", "description"],
        # Publisher facet (?org=<slug>).
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM links
            WHERE (name IS NULL OR name = '')
              AND (description IS NULL OR description = ''){facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        **_link_report_sql(
            "(name IS NULL OR name = '') AND (description IS NULL OR description = ''){org}",
        ),
    },
    {
        "key": "links-duplicate-urls",
        "label": "Duplicate URLs across datasets",
        "description": ("URLs that appear on more than one dataset.Click a URL to see every dataset that links to it."),
        "kind": "duplicate-urls",
        # Count: unique URLs that appear in 2+ datasets
        "count_sql": f"""SELECT COUNT(*) AS n FROM (
               SELECT url FROM links
               WHERE {_DUP_URLS_FILTER}
               GROUP BY url
               HAVING COUNT(DISTINCT dataset_id) > 1
             )""",
        # List: unique URLs with dataset + org counts, sorted by most-shared
        "list_sql": f"""SELECT url, COUNT(DISTINCT dataset_id) AS dataset_count,
                     COUNT(DISTINCT org_slug) AS org_count
              FROM links
              WHERE {_DUP_URLS_FILTER}
              GROUP BY url
              HAVING COUNT(DISTINCT dataset_id) > 1
              ORDER BY {{order_by}}
              LIMIT %s OFFSET %s""",
        # Detail: all links for one URL (used when ?url= is set)
        "detail_sql": f"""SELECT {_LINK_REPORT_COLS_L}
                FROM links l
                WHERE l.url = %s
                ORDER BY {{order_by}}
                LIMIT %s OFFSET %s""",
        "detail_count_sql": "SELECT COUNT(*) AS n FROM links WHERE url = %s",
    },
    {
        "key": "links-suspicious-redirects",
        "label": "Suspicious redirects",
        "description": "Links where 5 or more distinct URLs all redirect to the same destination — a likely sign of a catch-all redirect for content that no longer exists.",
        "kind": "suspicious-redirects",
        "percent_of": "links",
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT l.org_slug AS slug, l.org_display_name AS name,
                         COUNT(DISTINCT lcr.final_url) AS count
                    FROM link_check_results lcr
                    JOIN links l ON l.id = lcr.link_id
                    WHERE lcr.final_url IS NOT NULL
                      AND lcr.final_url != lcr.url
                      AND lcr.checked_at IS NOT NULL
                      AND lcr.final_url IN (
                        SELECT final_url FROM link_check_results
                        WHERE final_url IS NOT NULL AND final_url != url AND checked_at IS NOT NULL
                        GROUP BY final_url HAVING COUNT(DISTINCT url) >= 5
                      ){facet_and}
                    GROUP BY l.org_slug, l.org_display_name
                    ORDER BY count DESC, LOWER(l.org_display_name)""",
                "filter_sql": " AND bool_or(l.org_slug = %s)",
            },
        ],
        "count_sql": """SELECT COUNT(*) AS n FROM (
            SELECT lcr.final_url
            FROM link_check_results lcr
            JOIN links l ON l.id = lcr.link_id
            WHERE lcr.final_url IS NOT NULL
              AND lcr.final_url != lcr.url
              AND lcr.checked_at IS NOT NULL
            GROUP BY lcr.final_url
            HAVING COUNT(DISTINCT lcr.url) >= 5{org}
        ) sub""",
        "dashboard_count_sql": """SELECT COUNT(*) AS n
            FROM link_check_results
            WHERE final_url IS NOT NULL
              AND final_url != url
              AND checked_at IS NOT NULL
              AND final_url IN (
                SELECT final_url FROM link_check_results
                WHERE final_url IS NOT NULL AND final_url != url AND checked_at IS NOT NULL
                GROUP BY final_url HAVING COUNT(DISTINCT url) >= 5
              )""",
        "list_sql": """SELECT lcr.final_url,
                       COUNT(*) AS link_count,
                       COUNT(DISTINCT l.org_slug) AS org_count
                FROM link_check_results lcr
                JOIN links l ON l.id = lcr.link_id
                WHERE lcr.final_url IS NOT NULL
                  AND lcr.final_url != lcr.url
                  AND lcr.checked_at IS NOT NULL
                GROUP BY lcr.final_url
                HAVING COUNT(DISTINCT lcr.url) >= 5{org}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s""",
        "detail_sql": f"""SELECT {_LINK_REPORT_COLS_L}
                FROM link_check_results lcr
                JOIN links l ON l.id = lcr.link_id
                WHERE lcr.final_url = %s
                ORDER BY {{order_by}}
                LIMIT %s OFFSET %s""",
        "detail_count_sql": """SELECT COUNT(*) AS n
                FROM link_check_results lcr
                JOIN links l ON l.id = lcr.link_id
                WHERE lcr.final_url = %s""",
    },
]

# Each report's SQL carries a {key} placeholder per facet, replaced by the
# facet's filter_sql when a value is selected, or '' when not.


def report_facet_counts(report: dict, filters: dict[str, str] | None = None) -> dict[str, tuple[str, list]]:
    """Self-excluding sidebar facet option counts for one report, keyed by
    facet key → (sql, params): each facet's counts apply every other active
    facet's filter, omitting its own (only datasets-has-api has two).
    """
    filters = filters or {}
    entry = {}
    for facet in report.get("facets", []):
        frag, params = facet_where(_REPORT_FACET_CLAUSES, filters, exclude=facet["key"])
        sql = facet["counts_sql"]
        sql = sql.replace("{facet_where}", frag)
        sql = sql.replace("{facet_and}", f" AND {frag[len(' WHERE ') :]}" if frag else "")
        entry[facet["key"]] = (sql, params)
    return entry


# ── Memoised no-filter report data ───────────────────────────────────────
# No-filter counts and facet pools (run on every request to validate facet
# values) are build-time snapshots, memoised per report key — restart to
# refresh after a rebuild.


@functools.cache
def report_unfiltered_count(key: str) -> int:
    """No-filter row count for one report — memoised per report key."""
    report = next(r for r in REPORTS if r["key"] == key)
    stmt = report_stmts(report)
    return stmt["count"].get(*stmt["params"])["n"]


@functools.cache
def report_dashboard_count(key: str) -> int:
    """The dashboard card's count for one report — memoised per report key.

    Normally the same as report_unfiltered_count: one row per affected
    item. A report whose list groups by something other than the affected
    item itself (datasets-duplicate-content groups by content hash, so its
    own count/list must agree on *groups* for pagination) instead defines
    dashboard_count_sql for the card's own metric, and optionally
    dashboard_label when that metric's unit differs from the page's.
    """
    report = next(r for r in REPORTS if r["key"] == key)
    if "dashboard_count_sql" in report:
        return Query(report["dashboard_count_sql"]).get()["n"]
    return report_unfiltered_count(key)


@functools.cache
def report_unfiltered_options(key: str) -> dict[str, list[dict]]:
    """Executed no-filter facet option pools for one report, keyed by facet
    key — memoised per report key. Used by the report page's facet-value
    validation (run on every request, filtered or not)."""
    report = next(r for r in REPORTS if r["key"] == key)
    entry = report_facet_counts(report)
    return {facet_key: Query(sql).all(*params) for facet_key, (sql, params) in entry.items()}


def report_stmts(
    report: dict,
    filters: dict[str, str] | None = None,
    sort: str | None = None,
    dir_: str | None = None,
) -> dict:
    """Return {params, count, list} statements for a report, optionally
    filtered by facet values (facet key → selected value) and sorted."""
    filters = filters or {}
    count_sql = report["count_sql"]
    list_sql = report["list_sql"]
    params: list[str] = []
    for facet in report.get("facets", []):
        # Replace each facet's {key} placeholder with its filter_sql when a
        # value is selected, or '' when not. filter_sql may be a dict mapping
        # selected value → fragment (no %s param) or a plain string (appends value).
        value = filters.get(facet["key"])
        placeholder = "{" + facet["key"] + "}"
        if placeholder in count_sql or placeholder in list_sql:
            filter_sql = facet["filter_sql"]
            if isinstance(filter_sql, dict):
                fragment = filter_sql.get(value, "") if value else ""
                append_param = False
            else:
                fragment = filter_sql if value else ""
                append_param = bool(value)
            count_sql = count_sql.replace(placeholder, fragment)
            list_sql = list_sql.replace(placeholder, fragment)
            if append_param:
                params.append(value)

    kind = report.get("kind")
    if "{order_by}" in list_sql:
        if kind == "datasets":
            s = sort if sort in DATASET_REPORT_SORT else DATASET_REPORT_SORT_DEFAULT[0]
            d = dir_ if dir_ in ("asc", "desc") else DATASET_REPORT_SORT_DEFAULT[1]
            list_sql = list_sql.replace("{order_by}", _order_by_sql(DATASET_REPORT_SORT, s, d, "LOWER(title), id"))
        elif kind == "links":
            s = sort if sort in LINK_REPORT_SORT else LINK_REPORT_SORT_DEFAULT[0]
            d = dir_ if dir_ in ("asc", "desc") else LINK_REPORT_SORT_DEFAULT[1]
            list_sql = list_sql.replace("{order_by}", _order_by_sql(LINK_REPORT_SORT, s, d, "LOWER(dataset_title), id"))
        elif kind == "duplicate-content":
            s = sort if sort in DUPLICATE_CONTENT_SORT else DUPLICATE_CONTENT_SORT_DEFAULT[0]
            d = dir_ if dir_ in ("asc", "desc") else DUPLICATE_CONTENT_SORT_DEFAULT[1]
            list_sql = list_sql.replace("{order_by}", _order_by_sql(DUPLICATE_CONTENT_SORT, s, d, "title"))
        elif kind == "duplicate-urls":
            s = sort if sort in DUPLICATE_URL_SORT else DUPLICATE_URL_SORT_DEFAULT[0]
            d = dir_ if dir_ in ("asc", "desc") else DUPLICATE_URL_SORT_DEFAULT[1]
            list_sql = list_sql.replace("{order_by}", _order_by_sql(DUPLICATE_URL_SORT, s, d, "url"))
        elif kind == "suspicious-redirects":
            s = sort if sort in SUSPICIOUS_REDIRECT_SORT else SUSPICIOUS_REDIRECT_SORT_DEFAULT[0]
            d = dir_ if dir_ in ("asc", "desc") else SUSPICIOUS_REDIRECT_SORT_DEFAULT[1]
            list_sql = list_sql.replace("{order_by}", _order_by_sql(SUSPICIOUS_REDIRECT_SORT, s, d, "final_url"))

    entry = {
        "params": params,
        "count": Query(count_sql),
        "list": Query(list_sql),
    }
    return entry
