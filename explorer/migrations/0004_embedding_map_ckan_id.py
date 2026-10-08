"""Re-key embedding_map on the CKAN guid (dataset_ckan_id).

datasets is truncated and rebuilt (RESTART IDENTITY) on every CKAN ingest, so
the old integer FK cascaded away every stored vector. ckan_id is stable across
ingests; keying on it lets the existing embeddings survive. Backfills from
datasets.ckan_id via the old dataset_id before dropping that column, so no
current embeddings are lost. Reversible.

"""

from django.db import migrations, models


def _forward(apps, schema_editor):
    """Add and backfill dataset_ckan_id, then drop the integer key."""
    schema_editor.execute("ALTER TABLE embedding_map ADD COLUMN dataset_ckan_id text")
    schema_editor.execute(
        "UPDATE embedding_map m SET dataset_ckan_id = d.ckan_id FROM datasets d WHERE d.id = m.dataset_id",
    )
    schema_editor.execute("ALTER TABLE embedding_map ALTER COLUMN dataset_ckan_id SET NOT NULL")
    schema_editor.execute(
        "ALTER TABLE embedding_map ADD CONSTRAINT embedding_map_dataset_ckan_id_key UNIQUE (dataset_ckan_id)",
    )
    # Dropping the column also drops its FK and idx_embedding_map_dataset.
    schema_editor.execute("ALTER TABLE embedding_map DROP COLUMN dataset_id")


def _backward(apps, schema_editor):
    """Recreate the integer key + cascading FK from the current datasets."""
    schema_editor.execute("ALTER TABLE embedding_map ADD COLUMN dataset_id integer")
    schema_editor.execute(
        "UPDATE embedding_map m SET dataset_id = d.id FROM datasets d WHERE d.ckan_id = m.dataset_ckan_id",
    )
    # Orphans can exist (no FK); drop them before re-adding the FK.
    schema_editor.execute("DELETE FROM embedding_map WHERE dataset_id IS NULL")
    # Dropping the column also drops the unique constraint.
    schema_editor.execute("ALTER TABLE embedding_map DROP COLUMN dataset_ckan_id")
    schema_editor.execute(
        "ALTER TABLE embedding_map ADD CONSTRAINT embedding_map_dataset_id_fk"
        " FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE",
    )
    schema_editor.execute("CREATE INDEX idx_embedding_map_dataset ON embedding_map(dataset_id)")


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0003_mv_link_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(_forward, _backward),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="embeddingmap",
                    name="dataset_ckan_id",
                    field=models.TextField(unique=True),
                ),
                migrations.RemoveIndex(
                    model_name="embeddingmap",
                    name="idx_embedding_map_dataset",
                ),
                migrations.RemoveField(model_name="embeddingmap", name="dataset"),
            ],
        ),
    ]
