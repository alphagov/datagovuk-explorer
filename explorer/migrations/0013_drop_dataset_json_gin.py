"""Drop idx_dataset_json_gin.

0005 added it to accelerate JSONB `@>` containment for the metadata-value
filter, but _metadata_clause (explorer/queries/datasets.py) filters with
`->>` / jsonb_array_elements, which a GIN index on the whole column cannot
serve. It has never contributed a plan: the filter runs as a ~800ms seq
scan, while the `@>` form that would use the index measured ~2.5ms. The
filter is a low-traffic facet, so drop the index rather than carry ~225MB.
Recreate it in a migration if the filter is ever rewritten to `@>`.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0012_embedding_hnsw_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_dataset_json_gin",
            reverse_sql=(
                "CREATE INDEX IF NOT EXISTS idx_dataset_json_gin "
                "ON dataset_json USING GIN (json)"
            ),
        ),
    ]
