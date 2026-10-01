"""Squash of 0004–0012: add covering indexes; remove ok column from reviews/suggestions.

- idx_links_url_dataset_org: covering partial index for duplicate-URL report
- idx_datasets_views_desc: for top-by-views sort
- idx_datasets_reviews_cover: covering index for reviews/suggestions list join
- idx_links_host_lower: functional index for domain sort (LOWER(COALESCE(host,'')))
- idx_lcr_url_cover: covering index on link_check_results for join elimination
- uniq_reviews_dataset / uniq_suggestions_dataset: enforce one-row-per-dataset
  (replaces the DISTINCT ON dedup subquery; ok column removed)
"""

import django.db.models.functions.comparison
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('explorer', '0003_split_review_suggestion'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='link',
            index=models.Index(
                condition=models.Q(url__isnull=False) & ~models.Q(url=''),
                fields=['url', 'dataset', 'org_slug'],
                name='idx_links_url_dataset_org',
            ),
        ),
        migrations.AddIndex(
            model_name='dataset',
            index=models.Index(fields=['-views'], name='idx_datasets_views_desc'),
        ),
        migrations.AddIndex(
            model_name='dataset',
            index=models.Index(
                fields=['id'],
                include=['org_slug', 'org_display_name', 'title', 'theme_primary'],
                name='idx_datasets_reviews_cover',
            ),
        ),
        migrations.RunSQL(
            sql='DELETE FROM reviews WHERE NOT ok',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='DELETE FROM suggestions WHERE NOT ok',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveIndex(model_name='review', name='idx_reviews_dataset'),
        migrations.RemoveField(model_name='review', name='ok'),
        migrations.AddConstraint(
            model_name='review',
            constraint=models.UniqueConstraint(
                fields=['dataset'],
                include=['findability', 'resources'],
                name='uniq_reviews_dataset',
            ),
        ),
        migrations.RemoveIndex(model_name='suggestion', name='idx_suggestions_dataset'),
        migrations.RemoveField(model_name='suggestion', name='ok'),
        migrations.AddConstraint(
            model_name='suggestion',
            constraint=models.UniqueConstraint(
                fields=['dataset'],
                include=['theme', 'theme_confidence', 'tags', 'title', 'desc'],
                name='uniq_suggestions_dataset',
            ),
        ),
        migrations.AddIndex(
            model_name='link',
            index=models.Index(
                django.db.models.functions.text.Lower(
                    django.db.models.functions.comparison.Coalesce('host', models.Value(''))
                ),
                name='idx_links_host_lower',
            ),
        ),
        migrations.AddIndex(
            model_name='linkcheckresult',
            index=models.Index(
                fields=['url'],
                include=['ok', 'http_status', 'error', 'checked_at'],
                name='idx_lcr_url_cover',
            ),
        ),
    ]
