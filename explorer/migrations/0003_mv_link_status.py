"""Denormalised ``mv_link_status`` matview for the /links/status report.

The report reads every checked resource URL across all datasets — one row
per link occurrence. Doing that as a live join of ``links``,
``link_check_results``, ``datasets`` and ``organisations`` costs ~85-200 ms
per statement (the hash join of the two large tables spills to temp
regardless of how selective the filter is), and the page runs several per
request. This matview flattens that join once at build time; the query layer
then scans a single relation.

Columns are raw (no ``category`` expression): the derived outcome stays in
``explorer/queries/link_errors.py`` so the report's logic lives in one place.
``link_id`` is the underlying ``links.id`` — unique, so it carries the
unique index that ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` requires.

Refreshed by ``scripts/ingest_ckan.py`` (links/datasets/organisations) and
by ``scripts/check_links.py`` (link_check_results).

"""

from django.db import migrations

CREATE_MV = """
    CREATE MATERIALIZED VIEW mv_link_status AS
    SELECT
        l.id AS link_id,
        l.url,
        l.host,
        l.org_slug,
        COALESCE(NULLIF(o.display_name, ''), l.org_slug) AS publisher_name,
        l.dataset_title,
        l.resource_id,
        l.dataset_id,
        d.ckan_id,
        CASE WHEN d.id IS NULL THEN 'unknown'
             WHEN d.harvested = 1 THEN 'harvested'
             ELSE 'manual' END AS harvest_state,
        d.harvest_source_title,
        d.harvest_source_id,
        lcr.http_status,
        lcr.error,
        lcr.ok,
        lcr.checked_at
    FROM links l
    LEFT JOIN link_check_results lcr ON l.url = lcr.url
    LEFT JOIN datasets d ON d.id = l.dataset_id
    LEFT JOIN organisations o ON o.slug = l.org_slug
"""


class Migration(migrations.Migration):
    dependencies = [("explorer", "0002_reviews_suggestions_ckan_id")]

    operations = [
        migrations.RunSQL(
            sql=CREATE_MV,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS mv_link_status",
        ),
        # link_id backs CONCURRENTLY refreshes; the rest cover the facet
        # filters (domain, publisher, harvest state) and the status split.
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX mv_link_status_link_id_idx ON mv_link_status(link_id)",
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_link_id_idx",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX mv_link_status_host_idx ON mv_link_status(host)",
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_host_idx",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX mv_link_status_org_slug_idx ON mv_link_status(org_slug)",
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_org_slug_idx",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX mv_link_status_harvest_state_idx ON mv_link_status(harvest_state)",
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_harvest_state_idx",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX mv_link_status_ok_idx ON mv_link_status(ok)",
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_ok_idx",
        ),
        # One index per sort column, each paired with link_id (the ORDER BY
        # tie-breaker): the planner walks the index in order and stops after
        # LIMIT rows instead of seq-scanning + top-N sorting the whole view.
        migrations.RunSQL(
            sql="CREATE INDEX mv_link_status_url_sort_idx ON mv_link_status(LOWER(COALESCE(host, '')), link_id)",
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_url_sort_idx",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX mv_link_status_dataset_sort_idx "
                "ON mv_link_status(LOWER(COALESCE(dataset_title, '')), link_id)"
            ),
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_dataset_sort_idx",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX mv_link_status_publisher_sort_idx "
                "ON mv_link_status(LOWER(COALESCE(publisher_name, '')), link_id)"
            ),
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_publisher_sort_idx",
        ),
        migrations.RunSQL(
            sql=("CREATE INDEX mv_link_status_status_sort_idx ON mv_link_status(COALESCE(http_status, -1), link_id)"),
            reverse_sql="DROP INDEX IF EXISTS mv_link_status_status_sort_idx",
        ),
    ]
