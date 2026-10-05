from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0005_org_link_health"),
    ]

    operations = [
        migrations.AddField(
            model_name="harvestsource",
            name="dataset_count",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="harvestsource",
            name="last_run",
            field=models.TextField(blank=True, null=True),
        ),
    ]
