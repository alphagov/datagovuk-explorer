"""Convert collection_pages.page_last_updated from text to date.

The source values are date-only (``YYYY-MM-DD``); there is no time or zone
to resolve, so unlike the datasets/organisations/harvest timestamptz
conversions this uses a plain ``::date`` cast. Empty strings become NULL,
matching the other conversions. ``AlterField`` cannot carry a custom
``USING``, so this is a ``RunSQL`` wrapped in ``SeparateDatabaseAndState``
to keep the model state in sync.

Forward-only (no reverse_sql): migrations are squashed once this work lands
and an irreversible RunSQL fails loudly rather than doing something partial.
"""

from django.db import migrations, models

_FORWARD_SQL = (
    "ALTER TABLE collection_pages ALTER COLUMN page_last_updated TYPE date USING NULLIF(page_last_updated, '')::date"
)


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0009_harvest_source_timestamps"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=_FORWARD_SQL),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="collection",
                    name="page_last_updated",
                    field=models.DateField(blank=True, null=True),
                ),
            ],
        ),
    ]
