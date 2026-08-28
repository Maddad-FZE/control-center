from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_sitesettings_services_host"),
    ]

    operations = [
        migrations.AddField(
            model_name="updatestatus",
            name="install_step",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="updatestatus",
            name="install_step_index",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="updatestatus",
            name="install_total_steps",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="updatestatus",
            name="install_target_version",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
