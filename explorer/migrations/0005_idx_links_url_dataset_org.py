"""Add covering partial index on links(url, dataset_id, org_slug) WHERE url IS NOT NULL AND url != ''.

Eliminates the 40MB external-merge disk sort on the duplicate-URLs report list query
(GROUP BY url with COUNT(DISTINCT dataset_id/org_slug)), cutting ~550ms to ~100ms.
Also speeds up the suspicious-redirects join on links.url.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0004_idx_reviews_dataset_id_desc"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="link",
            index=models.Index(
                fields=["url", "dataset", "org_slug"],
                name="idx_links_url_dataset_org",
                condition=models.Q(url__isnull=False) & ~models.Q(url=""),
            ),
        ),
    ]
