from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0004_mv_org_aggregates"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE org_link_health (
                    org_slug    TEXT PRIMARY KEY,
                    link_health FLOAT
                );
            """,
            reverse_sql="DROP TABLE IF EXISTS org_link_health",
        ),
    ]
