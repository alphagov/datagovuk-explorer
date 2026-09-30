"""Partial covering index on suggestions(dataset_id, id DESC) INCLUDE (theme, theme_confidence).

The _SUGGESTIONS_DEDUP subquery (queries/suggestions.py) runs:
  SELECT DISTINCT ON (dataset_id) id, dataset_id, theme, theme_confidence, tags, title, "desc"
  FROM suggestions WHERE ok = true ORDER BY dataset_id, id DESC

Without this index Postgres does a seq scan + external merge sort (~28 MB to
disk per worker). The index allows reading rows in the right order for
DISTINCT ON without sorting. theme and theme_confidence are included so the
theme facet count query (which only needs those columns) can run as an
index-only scan.

tags, title and desc are large text and not included — heap fetches are
still needed for the full list query, but the sort cost is eliminated.

Also extends idx_datasets_reviews_cover to include theme_primary, which the
/suggestions list query needs as current_theme (d.theme_primary).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0008_idx_datasets_id_reviews_covering"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="suggestion",
            index=models.Index(
                fields=["dataset", "-id"],
                include=["theme", "theme_confidence"],
                name="idx_suggestions_dataset_cover",
                condition=models.Q(ok=True),
            ),
        ),
        migrations.RemoveIndex(
            model_name="dataset",
            name="idx_datasets_reviews_cover",
        ),
        migrations.AddIndex(
            model_name="dataset",
            index=models.Index(
                fields=["id"],
                include=["org_slug", "org_display_name", "title", "theme_primary"],
                name="idx_datasets_reviews_cover",
            ),
        ),
    ]
