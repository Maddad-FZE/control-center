from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_updatestatus_progress"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="title",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="tagline",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
