from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_drop_userprofile_theme"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="update_channel",
            field=models.CharField(
                choices=[("stable", "Stable"), ("dev", "Dev")],
                default="stable",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="updatestatus",
            name="installed_revision",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="updatestatus",
            name="latest_channel",
            field=models.CharField(
                choices=[("stable", "Stable"), ("dev", "Dev")],
                default="stable",
                max_length=8,
            ),
        ),
    ]
