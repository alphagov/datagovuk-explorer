from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0005_idx_links_url_dataset_org"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="dataset",
            index=models.Index(fields=["-views"], name="idx_datasets_views_desc"),
        ),
    ]
