"""Convert harvest_sources.created and last_run from text to timestamptz,
pinning naive UTC values to UTC.

The same conversion as 0007 (datasets) and 0008 (organisations): casting
naive text straight to timestamptz uses the session TimeZone, so naive
values are pinned with `AT TIME ZONE 'UTC'` while an explicit offset/Z is
honoured. `AlterField` cannot carry a custom `USING`, so this is a `RunSQL`
wrapped in `SeparateDatabaseAndState` to keep the model state in sync.

Both columns are space-separated naive UTC in the source data; `::timestamp`
accepts either `T` or space. Empty strings become NULL — 25 last_run rows
in the live data are empty, and an empty string is not a valid timestamp.

Forward-only (no reverse_sql): migrations are squashed once this work lands
and an irreversible RunSQL fails loudly rather than doing something partial.
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


_FORWARD_SQL = (
    "ALTER TABLE harvest_sources ALTER COLUMN created TYPE timestamptz "
    f"USING {_to_timestamptz('created')}, "
    "ALTER COLUMN last_run TYPE timestamptz "
    f"USING {_to_timestamptz('last_run')}"
)


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0008_organisation_created"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=_FORWARD_SQL),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="harvestsource",
                    name="created",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AlterField(
                    model_name="harvestsource",
                    name="last_run",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
