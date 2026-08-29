from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_sitesettings_title_tagline"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="wizard_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="wizard_notify",
            field=models.BooleanField(default=True),
        ),
    ]
