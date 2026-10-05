"""Convert datasets.metadata_created / metadata_modified from text to
timestamptz, pinning naive UTC values to UTC.

Casting naive text straight to timestamptz uses the session TimeZone (the
server default is Europe/London here), which would shift every summer
timestamp by an hour. The CASE below pins naive values with
`AT TIME ZONE 'UTC'` and honours an explicit offset/Z when one is present.
`AlterField` cannot carry that custom `USING` (Django hardcodes
`col::type`), so the conversion is a `RunSQL` wrapped in
`SeparateDatabaseAndState` to keep the model state in sync.

`mv_org_aggregates` selects `MAX(metadata_created)`, which blocks the ALTER
until the view is dropped; it is recreated (matching 0004) afterwards, with
`last_published` now a real timestamptz.

The reverse `to_char` is pinned with `AT TIME ZONE 'UTC'` so the instant is
preserved regardless of the migration session's timezone. It is lossy in
*format* only: space-separated and `Z`-suffixed rows come back in `T` form.
"""

from django.db import migrations, models

_DROP_MV = "DROP MATERIALIZED VIEW IF EXISTS mv_org_aggregates"

_CREATE_MV = """
    CREATE MATERIALIZED VIEW mv_org_aggregates AS
    SELECT org_slug,
           SUM(resource_count)   AS total_resources,
           SUM(views)            AS total_views,
           MAX(metadata_created) AS last_published
    FROM datasets
    GROUP BY org_slug;
    CREATE UNIQUE INDEX ON mv_org_aggregates(org_slug);
"""


def _to_timestamptz(col: str) -> str:
    return (
        "CASE\n"
        f"  WHEN {col} IS NULL OR {col} = '' THEN NULL\n"
        f"  WHEN {col} ~ '(Z|[+-][0-9]{{2}}:?[0-9]{{2}})$' THEN {col}::timestamptz\n"
        f"  ELSE {col}::timestamp AT TIME ZONE 'UTC'\n"
        "END"
    )


def _to_text(col: str) -> str:
    return f"to_char({col} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US')"


def _alter(table_col: str, to_type: str, using: str) -> str:
    table, col = table_col.split(".")
    return f"ALTER TABLE {table} ALTER COLUMN {col} TYPE {to_type} USING {using}"


_FORWARD_SQL = "\n".join(
    [
        _DROP_MV + ";",
        _alter("datasets.metadata_created", "timestamptz", _to_timestamptz("metadata_created")) + ";",
        _alter("datasets.metadata_modified", "timestamptz", _to_timestamptz("metadata_modified")) + ";",
        _CREATE_MV,
    ],
)

_REVERSE_SQL = "\n".join(
    [
        _DROP_MV + ";",
        _alter("datasets.metadata_created", "text", _to_text("metadata_created")) + ";",
        _alter("datasets.metadata_modified", "text", _to_text("metadata_modified")) + ";",
        _CREATE_MV,
    ],
)


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0006_harvest_sources_stats_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=_FORWARD_SQL, reverse_sql=_REVERSE_SQL),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="dataset",
                    name="metadata_created",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AlterField(
                    model_name="dataset",
                    name="metadata_modified",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
