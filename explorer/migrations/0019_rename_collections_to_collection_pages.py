"""Rename collections table to collection_pages; rename category column to collection."""

from django.db import migrations

_UP = """\
ALTER TABLE collections RENAME TO collection_pages;
ALTER TABLE collection_pages RENAME COLUMN category TO collection;
"""

_DOWN = """\
ALTER TABLE collection_pages RENAME COLUMN collection TO category;
ALTER TABLE collection_pages RENAME TO collections;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0018_collection_embeddings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(_UP, _DOWN)],
            state_operations=[
                migrations.AlterModelTable(
                    name="Collection",
                    table="collection_pages",
                ),
                migrations.RenameField(
                    model_name="Collection",
                    old_name="category",
                    new_name="collection",
                ),
            ],
        ),
    ]
