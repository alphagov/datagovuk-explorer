"""Re-key reviews and suggestions on the CKAN guid (dataset_ckan_id).

Adds dataset_ckan_id, backfills it from datasets.ckan_id via the old
integer dataset_id, then drops that column and its cascading FK. Reversible;
database and state operations are separated so the backfill can run between
the add and the drop.
"""

from django.db import migrations, models

# (table, unique-constraint name, INCLUDE columns, FK constraint name)
_TABLES = (
    (
        "reviews",
        "uniq_reviews_dataset",
        "findability, resources",
        "reviews_dataset_id_fk",
    ),
    (
        "suggestions",
        "uniq_suggestions_dataset",
        'theme, theme_confidence, tags, title, "desc"',
        "suggestions_dataset_id_fk",
    ),
)


def _forward(apps, schema_editor):
    """Add and backfill dataset_ckan_id, then drop the integer key."""
    for table, unique_name, include, _fk in _TABLES:
        schema_editor.execute(f"ALTER TABLE {table} ADD COLUMN dataset_ckan_id text")
        schema_editor.execute(
            f"UPDATE {table} t SET dataset_ckan_id = d.ckan_id"
            " FROM datasets d WHERE d.id = t.dataset_id",
        )
        schema_editor.execute(f"ALTER TABLE {table} ALTER COLUMN dataset_ckan_id SET NOT NULL")
        # Dropping the column also drops its unique constraint and FK.
        schema_editor.execute(f"ALTER TABLE {table} DROP COLUMN dataset_id")
        schema_editor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {unique_name}"
            f" UNIQUE (dataset_ckan_id) INCLUDE ({include})",
        )


def _backward(apps, schema_editor):
    """Recreate the integer key + cascading FK from the current datasets."""
    for table, unique_name, include, fk in _TABLES:
        schema_editor.execute(f"ALTER TABLE {table} ADD COLUMN dataset_id integer")
        schema_editor.execute(
            f"UPDATE {table} t SET dataset_id = d.id"
            " FROM datasets d WHERE d.ckan_id = t.dataset_ckan_id",
        )
        # Orphans can exist (no FK); drop them before NOT NULL / FK.
        schema_editor.execute(f"DELETE FROM {table} WHERE dataset_id IS NULL")
        schema_editor.execute(f"ALTER TABLE {table} ALTER COLUMN dataset_id SET NOT NULL")
        # Dropping the column also drops the unique constraint on it.
        schema_editor.execute(f"ALTER TABLE {table} DROP COLUMN dataset_ckan_id")
        schema_editor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {fk}"
            " FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE",
        )
        schema_editor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {unique_name}"
            f" UNIQUE (dataset_id) INCLUDE ({include})",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(_forward, _backward),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="review",
                    name="uniq_reviews_dataset",
                ),
                migrations.RemoveConstraint(
                    model_name="suggestion",
                    name="uniq_suggestions_dataset",
                ),
                migrations.RemoveField(model_name="review", name="dataset"),
                migrations.RemoveField(model_name="suggestion", name="dataset"),
                migrations.AddField(
                    model_name="review",
                    name="dataset_ckan_id",
                    field=models.TextField(),
                ),
                migrations.AddField(
                    model_name="suggestion",
                    name="dataset_ckan_id",
                    field=models.TextField(),
                ),
                migrations.AddConstraint(
                    model_name="review",
                    constraint=models.UniqueConstraint(
                        fields=["dataset_ckan_id"],
                        include=["findability", "resources"],
                        name="uniq_reviews_dataset",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="suggestion",
                    constraint=models.UniqueConstraint(
                        fields=["dataset_ckan_id"],
                        include=["theme", "theme_confidence", "tags", "title", "desc"],
                        name="uniq_suggestions_dataset",
                    ),
                ),
            ],
        ),
    ]
