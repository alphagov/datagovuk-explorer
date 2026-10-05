"""Convert organisations.created from text to timestamptz, pinning naive
UTC values to UTC.

The same conversion as 0007 (datasets): casting naive text straight to
timestamptz uses the session TimeZone, so naive values are pinned with
`AT TIME ZONE 'UTC'` while an explicit offset/Z is honoured. `AlterField`
cannot carry a custom `USING`, so this is a `RunSQL` wrapped in
`SeparateDatabaseAndState` to keep the model state in sync.

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
    "ALTER TABLE organisations ALTER COLUMN created TYPE timestamptz "
    f"USING {_to_timestamptz('created')}"
)


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0007_dataset_timestamps"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=_FORWARD_SQL),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="organisation",
                    name="created",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
