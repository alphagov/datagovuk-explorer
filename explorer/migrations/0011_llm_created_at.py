"""Convert reviews.created_at and suggestions.created_at from text to
timestamptz, pinning naive UTC values to UTC.

The same conversion as 0007 (datasets), 0008 (organisations) and 0009
(harvest sources): casting naive text straight to timestamptz uses the
session TimeZone, so naive values are pinned with `AT TIME ZONE 'UTC'`
while an explicit offset/Z is honoured. `AlterField` cannot carry a custom
`USING`, so this is a `RunSQL` wrapped in `SeparateDatabaseAndState` to
keep the model state in sync.

Both columns are written by the LLM pipeline with a trailing `Z` (the
offset branch), never read by the app. Forward-only (no reverse_sql):
migrations are squashed once this work lands and an irreversible RunSQL
fails loudly rather than doing something partial.
"""

from django.db import migrations, models


def _to_timestamptz(col: str) -> str:
    return (
        "CASE\n"
        f"  WHEN {col} IS NULL OR {col} = '' THEN NULL\n"
        f"  WHEN {col} ~ '(Z|[+-][0-9]{{2}}:?[0-9]{{2}})$' THEN {col}::timestamptz\n"
        f"  ELSE {col}::timestamp AT TIME ZONE 'UTC'\n"
        "END"
    )


_FORWARD_SQL = {
    table: (f"ALTER TABLE {table} ALTER COLUMN created_at TYPE timestamptz USING {_to_timestamptz('created_at')}")
    for table in ("reviews", "suggestions")
}


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0010_collection_page_last_updated"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=sql) for sql in _FORWARD_SQL.values()],
            state_operations=[
                migrations.AlterField(
                    model_name="review",
                    name="created_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AlterField(
                    model_name="suggestion",
                    name="created_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
