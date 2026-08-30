from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_userprofile_open_in_new_tab_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="kuma_username",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="kuma_password",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="kuma_setup_done",
            field=models.BooleanField(default=False),
        ),
    ]
