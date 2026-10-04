from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0003_datasets_harvested_idx"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE MATERIALIZED VIEW mv_org_aggregates AS
                SELECT org_slug,
                       SUM(resource_count)   AS total_resources,
                       SUM(views)            AS total_views,
                       MAX(metadata_created) AS last_published
                FROM datasets
                GROUP BY org_slug;
                CREATE UNIQUE INDEX ON mv_org_aggregates(org_slug);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS mv_org_aggregates",
        ),
    ]
