"""Data-quality report definitions (REPORTS) and their compiled
count/list statements."""

import functools

from .core import Query, facet_where

# --- Data-quality report definitions and their compiled count/list statements ---
# Each report is a count + paginated list query. `kind` tells the template
# which column set to render (orgs / datasets / links).
#
# Regular reports differ only in their WHERE clause: `_dataset_report_sql` /
# `_link_report_sql` build both statements from that one clause, so count
# and list can't drift. The special reports (duplicate-titles, duplicate-urls,
# has-api) keep hand-written SQL.
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

# Prefixed variants for the special reports' aliased queries (d./datasets./
# l. table aliases — the bare column names would be ambiguous with their
# joins).
_DATASET_REPORT_COLS_D = ", ".join(f"d.{c}" for c in DATASET_REPORT_COLS.split(", "))
_DATASET_REPORT_COLS_T = ", ".join(f"datasets.{c}" for c in DATASET_REPORT_COLS.split(", "))
_LINK_REPORT_COLS_L = ", ".join(f"l.{c}" for c in LINK_REPORT_COLS.split(", "))


def _dataset_report_sql(where: str) -> dict:
    """Count + list statements for a regular datasets report — one WHERE."""
    return {
        "where": where,
        "count_sql": f"SELECT COUNT(*) AS n FROM datasets WHERE {where}",
        "list_sql": (
            f"SELECT {DATASET_REPORT_COLS} FROM datasets WHERE {where}"
            f" ORDER BY {DATASET_REPORT_ORDER} LIMIT %s OFFSET %s"
        ),
    }


def _link_report_sql(where: str) -> dict:
    """Count + list statements for a regular links report — one WHERE."""
    return {
        "where": where,
        "count_sql": f"SELECT COUNT(*) AS n FROM links WHERE {where}",
        "list_sql": (
            f"SELECT {LINK_REPORT_COLS} FROM links WHERE {where} ORDER BY {LINK_REPORT_ORDER} LIMIT %s OFFSET %s"
        ),
    }


# --- "Datasets with an API" (positive finding) ---
# A dataset "has an API" when any of its links has an API-ish format, or the
# word "api" in its name/description. Deliberate choices:
#  - Includes WMS — a rendering service rather than a data-access API, but
#    many datasets match *only* via WMS and machine access is still access.
#  - A JSON resource only counts when its URL looks like a service endpoint
#    (Esri REST, CKAN datastore...), not a .json/.geojson file or an
#    export/download URL.
#  - Never `LIKE '%api%'` — the word-boundary regex avoids "rapid", etc.
_API_JSON_ENDPOINT_URL = (
    r"l.url ~ '/rest/services/'"
    r" OR l.url ~ '/api/'"
    r" OR l.url ~ 'ogcapi'"
    r" OR l.url ~ '/ogc/features'"
    r" OR l.url ~* '\?service='"
    r" OR l.url ~* '\?request='"
    r" OR l.url ~* '\?f=json'"
    r" OR l.url ~* '\?format=json'"
    r" OR l.host ~* '(^|\.)api\.'"
)
_API_JSON_FILE_URL = (
    r"l.url ~* '\.(json|geojson|jsonl|csv|xml|zip|xlsx|xls|kml|txt)(\?|$)'"
    r" OR l.url ~ '/exports/'"
    r" OR l.url ~ '/download/'"
    r" OR l.url ~* '\?accessType=DOWNLOAD'"
)
# CKAN's datastore search ends in .json but is a query API — exempt from
# the terminal-file rule above.
_API_JSON_IS_API = f"""l.format_norm = 'JSON' AND (
  l.url ~ '/api/action/datastore/search'
  OR (({_API_JSON_ENDPOINT_URL}) AND NOT ({_API_JSON_FILE_URL}))
)"""

# ILIKE patterns are doubled (%%…%%) because psycopg3 treats a single % in
# a parameterized statement as a placeholder (see queries/core.py).
_API_SIGNAL_SQL = (
    "l.format_norm ILIKE '%%arcgis rest%%'"
    " OR l.format_norm ILIKE '%%wms%%'"
    " OR l.format_norm ILIKE '%%wfs%%'"
    " OR l.format_norm ILIKE '%%ogc api%%'"
    " OR l.format_norm ILIKE '%%api%%'"
    " OR l.format_norm = 'CSW'"
    " OR l.format_norm ILIKE '%%georss%%'"
    f" OR ({_API_JSON_IS_API})"  # JSON counts only when the URL is a service endpoint (see above)
    r" OR l.name ~* '\mapi\M'"
    r" OR l.description ~* '\mapi\M'"
)

# Per-link classification of *why* a link matched the API signal — the
# "API type" facet. Order matters: specific formats precede the generic
# '%api%' bucket, so combined formats like "WMS/WFS" land in one bucket.
# Links matching only on name/description fall to 'unknown'.
_API_TYPE_CASE = (
    "CASE"
    " WHEN l.format_norm ILIKE '%%arcgis rest%%' THEN 'arcgis-rest'"
    " WHEN l.format_norm ILIKE '%%ogc api%%' THEN 'ogc-api'"
    " WHEN l.format_norm ILIKE '%%wms%%' THEN 'wms'"
    " WHEN l.format_norm ILIKE '%%wfs%%' THEN 'wfs'"
    " WHEN l.format_norm ILIKE '%%api%%' THEN 'api'"
    " WHEN l.format_norm = 'CSW' THEN 'csw'"
    " WHEN l.format_norm ILIKE '%%georss%%' THEN 'georss'"
    f" WHEN ({_API_JSON_IS_API}) THEN 'json'"
    r" WHEN l.name ~* '\mapi\M' OR l.description ~* '\mapi\M' THEN 'unknown'"
    " ELSE 'unknown' END"
)

# Display labels for the API-type facet buckets (used in the facet option SQL).
_API_TYPE_LABEL_CASE = (
    "CASE t.api_type"
    " WHEN 'arcgis-rest' THEN 'ArcGIS REST'"
    " WHEN 'wms' THEN 'WMS'"
    " WHEN 'wfs' THEN 'WFS'"
    " WHEN 'json' THEN 'JSON'"
    " WHEN 'ogc-api' THEN 'OGC API'"
    " WHEN 'api' THEN 'API'"
    " WHEN 'csw' THEN 'CSW'"
    " WHEN 'georss' THEN 'GeoRSS'"
    " ELSE 'Unknown' END"
)

# The URL filter shared by links-duplicate-urls' count + list statements.
_DUP_URLS_FILTER = "url IS NOT NULL AND url != ''"

# EXISTS filter re-applying the API signal for one API type — shared by the
# api_type facet's filter_sql and _report_api_type_clause. References the
# outer `datasets` table by design.
_API_TYPE_FILTER_EXISTS = f"""EXISTS (
   SELECT 1 FROM links l
   WHERE l.dataset_id = datasets.id
     AND ({_API_SIGNAL_SQL})
     AND ({_API_TYPE_CASE}) = %s
 )"""

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


def _report_api_type_clause(filters: dict, exclude: str | None) -> tuple[list, list]:
    """api_type facet WHERE fragment — EXISTS re-applying the API signal."""
    if exclude == "api_type":
        return [], []
    at = filters.get("api_type")
    if at:
        return [_API_TYPE_FILTER_EXISTS], [at]
    return [], []


_REPORT_FACET_CLAUSES = {
    "org": _report_org_clause,
    "api_type": _report_api_type_clause,
}

REPORTS = [
    {
        "key": "datasets-no-description",
        "label": "Datasets with no description",
        "description": ("Datasets with a missing or empty description — nothing to tell you what the data is about."),
        "kind": "datasets",
        **_dataset_report_sql("notes IS NULL OR TRIM(notes) = ''"),
    },
    {
        "key": "datasets-short-description",
        "label": "Datasets with a short description",
        "description": (
            "Datasets whose description is under 80 characters — too little to say what the data is about."
        ),
        "kind": "datasets",
        **_dataset_report_sql(
            "notes IS NOT NULL AND TRIM(notes) != '' AND LENGTH(TRIM(notes)) < 80",
        ),
    },
    {
        "key": "datasets-short-title",
        "label": "Datasets with a short title",
        "description": ("Datasets whose title is under 20 characters — too little to say what the data is about."),
        "kind": "datasets",
        **_dataset_report_sql(
            "title IS NOT NULL AND TRIM(title) != '' AND LENGTH(TRIM(title)) < 20",
        ),
    },
    {
        "key": "datasets-withdrawn",
        "label": "Datasets that have been withdrawn",
        "description": (
            "Datasets marked as withdrawn, retired or no longer available in their "
            "title or description — usually with a pointer to a replacement."
        ),
        "kind": "datasets",
        # The LIKE patterns are doubled (%%…%%) — see the psycopg3 binding
        # rule in queries/core.py.
        **_dataset_report_sql(
            "title LIKE '%%withdrawn%%'"
            " OR notes LIKE '%%dataset has been withdrawn%%'"
            " OR notes LIKE '%%no longer updated and has been retired%%'"
            " OR notes LIKE '%%record has been retired%%'"
            " OR notes LIKE '%%dataset has been retired%%'",
        ),
    },
    {
        "key": "datasets-duplicate-titles",
        "label": "Datasets with duplicate titles",
        "description": (
            "Datasets that share an identical title with another dataset from the same "
            "organisation — usually a dataset that was re-published without removing "
            "the old copy."
        ),
        "kind": "datasets",
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM (
              SELECT d.org_slug, d.org_display_name,
                     COUNT(*) OVER (PARTITION BY d.org_slug, lower(trim(d.title))) AS c
              FROM datasets d
              WHERE d.title IS NOT NULL AND TRIM(d.title) != ''
            ) sub
            WHERE c > 1{facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        # Window-function COUNT(*) OVER per org/title pair — one pass over
        # datasets, no self-join. {org} is the publisher facet filter placeholder.
        "count_sql": """SELECT COUNT(*) AS n FROM (
               SELECT d.id, COUNT(*) OVER (PARTITION BY org_slug, lower(trim(title))) AS c
               FROM datasets d
               WHERE title IS NOT NULL AND TRIM(title) != ''{org}
             ) WHERE c > 1""",
        "list_sql": f"""SELECT {_DATASET_REPORT_COLS_D}
              FROM datasets d
              JOIN (
                SELECT id FROM (
                  SELECT d.id, COUNT(*) OVER (PARTITION BY org_slug, lower(trim(title))) AS c
                  FROM datasets d
                  WHERE title IS NOT NULL AND TRIM(title) != ''{{org}}
                ) WHERE c > 1
              ) dups ON dups.id = d.id
              ORDER BY LOWER(d.org_display_name), LOWER(d.title), d.metadata_created, d.id
              LIMIT %s OFFSET %s""",
    },
    {
        "key": "links-no-url",
        "label": "Links with no URL",
        "description": "Links with a missing or empty download URL.",
        "kind": "links",
        # Columns the WHERE clause guarantees to be empty — hidden so the
        # table doesn't show a column of dashes (shared links table).
        "hidden_cols": ["url"],
        # Publisher facet (?org=<slug>) — same pattern as datasets-no-links.
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM links WHERE (url IS NULL OR url = ''){facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        **_link_report_sql("(url IS NULL OR url = ''){org}"),
    },
    {
        "key": "links-bad-url",
        "label": "Links with unparseable URLs",
        "description": (
            "Links with a URL that can't be parsed into a valid web address — "
            "often HTML or free text pasted into the URL field."
        ),
        "kind": "links",
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM links WHERE (url IS NOT NULL AND url != '') AND host IS NULL{facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        **_link_report_sql("(url IS NOT NULL AND url != '') AND host IS NULL{org}"),
    },
    {
        "key": "links-no-format",
        "label": "Links with no format",
        "description": "Links with no file format recorded.",
        "kind": "links",
        "hidden_cols": ["format"],
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                "counts_sql": """SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM links WHERE (format_norm IS NULL OR format_norm = ''){facet_and}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
        ],
        **_link_report_sql("(format_norm IS NULL OR format_norm = ''){org}"),
    },
    {
        "key": "links-no-name",
        "label": "Links with no name",
        "description": (
            "Links with neither a descriptive name nor a description — nothing to tell you what they contain."
        ),
        "kind": "links",
        "hidden_cols": ["name", "description"],
        # Publisher facet (?org=<slug>) — same pattern as links-no-url.
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
        "description": (
            "URLs that appear on more than one dataset. Most are service endpoints "
            "(WMS/WFS) or portal homepages published by the same organisation, but a "
            "few span multiple organisations. Click a URL to see every dataset that "
            "links to it."
        ),
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
              ORDER BY dataset_count DESC, url
              LIMIT %s OFFSET %s""",
        # Detail: all links for one URL (used when ?url= is set)
        "detail_sql": f"""SELECT {_LINK_REPORT_COLS_L}
                FROM links l
                WHERE l.url = %s
                ORDER BY LOWER(l.org_display_name), LOWER(l.dataset_title), l.id
                LIMIT %s OFFSET %s""",
        "detail_count_sql": "SELECT COUNT(*) AS n FROM links WHERE url = %s",
    },
    {
        "key": "datasets-has-api",
        "label": "Datasets with an API",
        "description": (
            "Datasets with at least one link that offers programmatic access "
            "to its data — a service endpoint (ArcGIS REST, WMS, WFS, OGC API, "
            "CSW, GeoRSS), a JSON link whose URL is a service endpoint "
            "(not a .json file download), or a link named or described as "
            "an API. A positive finding: these datasets expose their data to "
            "software, not just the download button. The API links column "
            "shows which link(s) matched and why."
        ),
        "kind": "datasets",
        # Tells the report template to render the matched-resources column
        # (and the route to parse the jsonb aggregate into a list).
        "show_api_links": True,
        # Two single-select facets — Publisher (org slug) and API type. Both
        # filter the outer `datasets` table (deliberately unaliased).
        "facets": [
            {
                "key": "org",
                "label": "Publisher",
                # Self-excluding option counts: {facet_and} is the api_type
                # filter when active (the org facet's own filter is excluded).
                "counts_sql": f"""SELECT org_slug AS slug, org_display_name AS name, COUNT(*) AS count
            FROM datasets
            WHERE EXISTS (
              SELECT 1 FROM links l WHERE l.dataset_id = datasets.id AND ({_API_SIGNAL_SQL})
            ){{facet_and}}
            GROUP BY org_slug, org_display_name
            ORDER BY count DESC, LOWER(org_display_name)""",
                "filter_sql": " AND org_slug = %s",
            },
            {
                # A dataset is counted under every API type its matched links
                # classify as, so the counts don't sum to the report total.
                "key": "api_type",
                "label": "API type",
                # {facet_where} is the org filter when active (api_type
                # excluded), joined to datasets so org_slug resolves.
                "counts_sql": f"""SELECT t.api_type AS slug,
                          {_API_TYPE_LABEL_CASE} AS name,
                          COUNT(DISTINCT t.dataset_id) AS count
                   FROM (
                     SELECT l.dataset_id, {_API_TYPE_CASE} AS api_type
                     FROM links l
                     WHERE ({_API_SIGNAL_SQL})
                   ) t
                   JOIN datasets ON datasets.id = t.dataset_id
                   {{facet_where}}
                   GROUP BY t.api_type
                   ORDER BY count DESC, t.api_type""",
                # Re-applies the signal WHERE so only links that match the
                # report classify into a bucket.
                "filter_sql": f" AND {_API_TYPE_FILTER_EXISTS}",
            },
        ],
        "count_sql": f"""SELECT COUNT(*) AS n FROM datasets
               WHERE EXISTS (
                 SELECT 1 FROM links l WHERE l.dataset_id = datasets.id AND ({_API_SIGNAL_SQL})
               ){{org}}{{api_type}}""",
        # One row per dataset; api_links aggregates every matched link
        # (name/format/url) so the template can show why each matched.
        "list_sql": f"""SELECT {_DATASET_REPORT_COLS_T},
                     COALESCE(ml.api_links, '[]'::jsonb) AS api_links
              FROM datasets
              LEFT JOIN (
                SELECT l.dataset_id,
                       jsonb_agg(jsonb_build_object(
                         'name', l.name,
                         'format', l.format_norm,
                         'url', l.url
                       ) ORDER BY l.position NULLS LAST, l.id) AS api_links
                FROM links l
                WHERE ({_API_SIGNAL_SQL})
                GROUP BY l.dataset_id
              ) ml ON ml.dataset_id = datasets.id
              WHERE ml.api_links IS NOT NULL{{org}}{{api_type}}
              ORDER BY LOWER(datasets.org_display_name), LOWER(datasets.title), datasets.id
              LIMIT %s OFFSET %s""",
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
def report_unfiltered_options(key: str) -> dict[str, list[dict]]:
    """Executed no-filter facet option pools for one report, keyed by facet
    key — memoised per report key. Used by the report page's facet-value
    validation (run on every request, filtered or not)."""
    report = next(r for r in REPORTS if r["key"] == key)
    entry = report_facet_counts(report)
    return {facet_key: Query(sql).all(*params) for facet_key, (sql, params) in entry.items()}


def report_stmts(report: dict, filters: dict[str, str] | None = None) -> dict:
    """Return {params, count, list} statements for a report, optionally
    filtered by facet values (facet key → selected value)."""
    filters = filters or {}
    count_sql = report["count_sql"]
    list_sql = report["list_sql"]
    params: list[str] = []
    for facet in report.get("facets", []):
        # Replace each facet's {key} placeholder with its filter_sql when a
        # value is selected, or '' when not.
        value = filters.get(facet["key"])
        placeholder = "{" + facet["key"] + "}"
        if placeholder in count_sql or placeholder in list_sql:
            count_sql = count_sql.replace(
                placeholder,
                facet["filter_sql"] if value else "",
            )
            list_sql = list_sql.replace(
                placeholder,
                facet["filter_sql"] if value else "",
            )
            if value:
                params.append(value)

    entry = {
        "params": params,
        "count": Query(count_sql),
        "list": Query(list_sql),
    }
    return entry
