"""link_errors table + indexes — the /links/errors report.

Mirrors data/errors-current.csv one row per check result: TRUNCATE + reload
by scripts/ingest_link_errors.py, same
ownership as the reviews table (ingest script, not the build). Fidelity
over trimming: every CSV column is kept, including the CSV-derived
`datagovuk_url` — the report links to it when a package is absent from the
datasets snapshot (the LEFT JOIN can't supply /dataset/{org}/{id} then).

package_id is a plain text column, NOT an FK: ~3.6% of the CSV's packages
are missing from `datasets`, and an FK would make ingest fail on them.

Indexes cover the query layer's workload — the /links/errors facets group
by category, http_status, org_name and the package/harvested join
(package_id), and the default sort is checked_at — plus resource_id (the
checker's key). The four doc-specified indexes use the documented names;
org_name/http_status are added for the facet aggregates.
"""

from django.db import migrations, models

INDEXES = [
    "CREATE INDEX IF NOT EXISTS link_errors_package_id_idx  ON link_errors(package_id)",
    "CREATE INDEX IF NOT EXISTS link_errors_resource_id_idx ON link_errors(resource_id)",
    "CREATE INDEX IF NOT EXISTS link_errors_category_idx    ON link_errors(category)",
    "CREATE INDEX IF NOT EXISTS link_errors_checked_at_idx  ON link_errors(checked_at)",
    "CREATE INDEX IF NOT EXISTS link_errors_org_name_idx    ON link_errors(org_name)",
    "CREATE INDEX IF NOT EXISTS link_errors_http_status_idx ON link_errors(http_status)",
]


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0008_temporal_periods_table"),
    ]

    operations = [
        migrations.CreateModel(
            name="LinkError",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("datagovuk_url", models.TextField(blank=True, null=True)),
                ("package_id", models.TextField()),
                ("package_name", models.TextField(blank=True, null=True)),
                ("package_metadata_created", models.TextField(blank=True, null=True)),
                ("package_metadata_modified", models.TextField(blank=True, null=True)),
                ("guid", models.TextField(blank=True, null=True)),
                ("resource_id", models.TextField()),
                ("resource_url", models.TextField(blank=True, null=True)),
                ("resource_created", models.TextField(blank=True, null=True)),
                ("resource_last_modified", models.TextField(blank=True, null=True)),
                ("resource_metadata_modified", models.TextField(blank=True, null=True)),
                ("org_name", models.TextField(blank=True, null=True)),
                ("org_id", models.TextField(blank=True, null=True)),
                ("http_status", models.IntegerField(blank=True, null=True)),
                ("category", models.TextField(blank=True, null=True)),
                ("error_detail", models.TextField(blank=True, null=True)),
                ("to_delete", models.BooleanField()),
                ("checked_at", models.TextField()),
            ],
            options={
                "db_table": "link_errors",
            },
        ),
        migrations.RunSQL(sql=INDEXES, reverse_sql=migrations.RunSQL.noop),
    ]
