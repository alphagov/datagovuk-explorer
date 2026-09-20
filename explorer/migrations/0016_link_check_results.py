from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0015_dataset_content_hash"),
    ]

    operations = [
        migrations.CreateModel(
            name="LinkCheckResult",
            fields=[
                ("url", models.TextField(primary_key=True, serialize=False)),
                ("checked_at", models.TextField()),
                ("method", models.TextField(blank=True, null=True)),
                ("ok", models.BooleanField(blank=True, null=True)),
                ("http_status", models.IntegerField(blank=True, null=True)),
                ("final_url", models.TextField(blank=True, null=True)),
                ("error", models.TextField(blank=True, null=True)),
            ],
            options={
                "db_table": "link_check_results",
            },
        ),
    ]
