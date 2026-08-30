from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_sitesettings_wizard"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="open_in_new_tab_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Service ids that should skip the in-app overlay",
            ),
        ),
    ]
