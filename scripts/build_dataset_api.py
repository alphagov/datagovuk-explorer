"""Populate the dataset_api summary table from links + dataset signals.

Reads the existing datasets and links tables (populated by ingest_ckan.py)
and writes one row per dataset that has an API signal, with its api_category.
Idempotent: TRUNCATE + INSERT, so re-running is always safe.

Usage: python -m scripts.build_dataset_api
"""

from scripts.db import connect, database_url

DATABASE_URL = database_url()

# API detection SQL for the build-time snapshot — single % for ILIKE (no
# psycopg3 params; db.exec skips placeholder parsing). Keep in sync with
# explorer/queries/reports.py (_API_SIGNAL_SQL / _API_TYPE_CASE).

_BUILD_API_SIGNAL = (
    "l.format_norm ILIKE '%arcgis rest%'"
    " OR l.format_norm ILIKE '%wms%'"
    " OR l.format_norm ILIKE '%wfs%'"
    " OR l.format_norm ILIKE '%ogc api%'"
    " OR (l.format_norm ILIKE '%api%' AND l.format_norm NOT ILIKE '%mapinfo%')"
    " OR l.format_norm ILIKE '%sparql%'"
    " OR l.format_norm = 'CSW'"
    " OR l.format_norm ILIKE '%georss%'"
    r" OR l.url ~ '/rest/services/'"
    r" OR l.url ~* '\?service='"
    r" OR l.url ~* '\?request='"
    r" OR l.url ~* '\?f=json'"
    r" OR l.url ~ 'ogcapi'"
    r" OR l.url ~* '/wms(\?|$)'"
    r" OR l.url ~* '/wfs(\?|$)'"
    r" OR l.url ~ '/ogc/features'"
    r" OR l.name ~* '\mapi\M'"
    r" OR l.name ~* '\msparql\M'"
    r" OR l.name ~* '\mwfs\M'"
    r" OR l.name ~* '\mwms\M'"
    r" OR l.description ~* '\mapi\M'"
    r" OR l.description ~* '\msparql\M'"
)

_BUILD_API_TYPE_CASE = (
    "CASE"
    " WHEN l.format_norm ILIKE '%arcgis rest%' THEN 'arcgis-rest'"
    " WHEN l.format_norm ILIKE '%ogc api%' THEN 'ogc-api'"
    " WHEN l.format_norm ILIKE '%sparql%' THEN 'sparql'"
    " WHEN l.format_norm ILIKE '%wms%' THEN 'wms'"
    " WHEN l.format_norm ILIKE '%wfs%' THEN 'wfs'"
    " WHEN l.format_norm ILIKE '%api%' AND l.format_norm NOT ILIKE '%mapinfo%' THEN 'api'"
    " WHEN l.format_norm = 'CSW' THEN 'csw'"
    " WHEN l.format_norm ILIKE '%georss%' THEN 'georss'"
    r" WHEN l.url ~ '/rest/services/' THEN 'arcgis-rest'"
    r" WHEN l.url ~* '\?service=WMS' THEN 'wms'"
    r" WHEN l.url ~* '\?service=WFS' THEN 'wfs'"
    r" WHEN l.url ~* '\?service=' OR l.url ~* '\?request=' OR l.url ~* '\?f=json' THEN 'ogc-api'"
    r" WHEN l.url ~* '/wms(\?|$)' THEN 'wms'"
    r" WHEN l.url ~* '/wfs(\?|$)' THEN 'wfs'"
    r" WHEN l.url ~ '/ogc/features' OR l.url ~ 'ogcapi' THEN 'ogc-api'"
    r" WHEN l.name ~* 'ogc api' THEN 'ogc-api'"
    r" WHEN l.name ~* '\msparql\M' OR l.description ~* '\msparql\M' THEN 'sparql'"
    r" WHEN l.name ~* '\mwfs\M' OR l.description ~* '\mwfs\M' THEN 'wfs'"
    r" WHEN l.name ~* '\mwms\M' OR l.description ~* '\mwms\M' THEN 'wms'"
    r" WHEN l.name ~* '\mapi\M' OR l.description ~* '\mapi\M' THEN 'unknown'"
    " ELSE 'unknown' END"
)

_BUILD_MAP_LAYER_TYPES = "('arcgis-rest', 'wms', 'wfs', 'ogc-api', 'csw', 'georss')"

INSERT_DATASET_API_SQL = f"""
INSERT INTO dataset_api (dataset_id, api_category)
SELECT
    datasets.id,
    CASE WHEN EXISTS (
        SELECT 1 FROM links l
        WHERE l.dataset_id = datasets.id
          AND ({_BUILD_API_SIGNAL})
          AND ({_BUILD_API_TYPE_CASE}) IN {_BUILD_MAP_LAYER_TYPES}
    ) THEN 'map-layers' ELSE 'data-apis' END AS api_category
FROM datasets
WHERE EXISTS (
    SELECT 1 FROM links l
    WHERE l.dataset_id = datasets.id
      AND ({_BUILD_API_SIGNAL})
) OR (datasets.title ~* '\\mapi\\M' OR datasets.notes ~* '\\mapi\\M')
"""


def _populate_dataset_api(db) -> int:
    """Populate the dataset_api summary table from links + dataset signals.
    Returns the row count inserted."""
    db.exec(INSERT_DATASET_API_SQL)
    row = db.prepare("SELECT COUNT(*) AS n FROM dataset_api").get()
    return row["n"]


def main() -> None:
    """Rebuild the dataset_api table (TRUNCATE + INSERT).

    Runs in seconds against the existing datasets/links data — use this
    when tweaking the API detection algorithm without a full rebuild."""

    db = connect(DATABASE_URL)
    try:
        db.exec("TRUNCATE TABLE dataset_api")
        n = _populate_dataset_api(db)
        by_cat = db.prepare(
            "SELECT api_category, COUNT(*) AS n FROM dataset_api GROUP BY api_category ORDER BY n DESC",
        ).all()
        print(f"dataset_api: {n} datasets")
        for row in by_cat:
            print(f"  {row['api_category']}: {row['n']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
