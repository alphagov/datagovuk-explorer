"""Extend idx_suggestions_dataset_cover to include tags, title, desc.

Avg column sizes (from data): tags=92, title=58, desc=385 bytes — all under
Postgres's 2 KB TOAST threshold, so they store inline in the index. Adding
them turns the _SUGGESTIONS_DEDUP scan into an index-only scan, eliminating
the ~28 MB external merge sort per worker that dominates the /suggestions
list query.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0009_idx_suggestions_covering"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="suggestion",
            name="idx_suggestions_dataset_cover",
        ),
        migrations.AddIndex(
            model_name="suggestion",
            index=models.Index(
                fields=["dataset", "-id"],
                include=["theme", "theme_confidence", "tags", "title", "desc"],
                name="idx_suggestions_dataset_cover",
                condition=models.Q(ok=True),
            ),
        ),
    ]
