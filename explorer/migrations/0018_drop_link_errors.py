from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("explorer", "0016_link_check_results"),
    ]

    operations = [
        migrations.DeleteModel(name="LinkError"),
    ]
