"""Remove ok column; enforce one-row-per-dataset with a UNIQUE covering index.

The ingest scripts use TRUNCATE + COPY with one file per dataset, so there has
always been at most one row per dataset_id. The DISTINCT ON dedup subquery that
every read query used existed to handle a case that never occurred in practice.

This migration:
- deletes the 19 ok:false rows that were kept as sentinel records
- drops the two partial indexes per table that were built around the dedup sort
- removes the ok column from both tables
- adds a UNIQUE constraint (with INCLUDE covering columns) on dataset_id

After this migration the read queries can reference reviews/suggestions directly
without a dedup subquery, and the UNIQUE constraint enforces the invariant at the
schema level.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0010_idx_suggestions_full_cover"),
    ]

    operations = [
        # Remove ok:false rows before dropping the column.
        migrations.RunSQL(
            "DELETE FROM reviews WHERE NOT ok",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DELETE FROM suggestions WHERE NOT ok",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Drop the dedup-oriented partial indexes on reviews.
        migrations.RemoveIndex(model_name="review", name="idx_reviews_dataset"),
        migrations.RemoveIndex(model_name="review", name="idx_reviews_dataset_id_desc"),
        migrations.RemoveField(model_name="review", name="ok"),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.UniqueConstraint(
                fields=["dataset"],
                include=["findability", "resources"],
                name="uniq_reviews_dataset",
            ),
        ),
        # Drop the dedup-oriented partial indexes on suggestions.
        migrations.RemoveIndex(model_name="suggestion", name="idx_suggestions_dataset"),
        migrations.RemoveIndex(model_name="suggestion", name="idx_suggestions_dataset_cover"),
        migrations.RemoveField(model_name="suggestion", name="ok"),
        migrations.AddConstraint(
            model_name="suggestion",
            constraint=models.UniqueConstraint(
                fields=["dataset"],
                include=["theme", "theme_confidence", "tags", "title", "desc"],
                name="uniq_suggestions_dataset",
            ),
        ),
    ]
