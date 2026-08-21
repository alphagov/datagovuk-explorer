"""temporal_periods table; drop the jsonb + dead text columns.

Replaces the temporal_coverage-from/to/granularity text columns and the
temporal_periods jsonb column (migration 0006) on datasets with a real
normalised table: one row per coverage period ([from_year, to_year],
either year NULL for open-ended coverage) plus a `source` column
('declared' | 'title' | 'resource') recording where the period came from
— the publisher's temporal_coverage-from/to, or an inference from the
dataset title / a resource name at build time. The facet layer queries
this table directly (no jsonb anywhere); the detail page reads the raw
JSON for declared datasets and this table for suggested ones.

Drops the jsonb column and the write-only text columns. Nothing reads
them: the detail page renders from dataset_json, the /metadata report
counts fields from the JSON, and the facet uses the table (which the
build now populates). temporal_granularity survives in the JSON.

Composite PK (dataset_id, position) matches the model's
CompositePrimaryKey; the FK is db_index=False per the repo's
index-ownership rule (0003 owns the indexes).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0007_harvest_sources"),
    ]

    operations = [
        migrations.CreateModel(
            name="TemporalPeriod",
            fields=[
                (
                    "dataset",
                    models.ForeignKey(
                        db_column="dataset_id",
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="explorer.dataset",
                    ),
                ),
                ("position", models.IntegerField()),
                ("from_year", models.IntegerField(blank=True, null=True)),
                ("to_year", models.IntegerField(blank=True, null=True)),
                ("source", models.TextField()),
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "dataset",
                        "position",
                        blank=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
            ],
            options={
                "db_table": "temporal_periods",
            },
        ),
        migrations.RemoveField(
            model_name="dataset",
            name="temporal_coverage_from",
        ),
        migrations.RemoveField(
            model_name="dataset",
            name="temporal_coverage_to",
        ),
        migrations.RemoveField(
            model_name="dataset",
            name="temporal_granularity",
        ),
        migrations.RemoveField(
            model_name="dataset",
            name="temporal_periods",
        ),
    ]
