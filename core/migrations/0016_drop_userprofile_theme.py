from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_sitesettings_default_theme"),
    ]

    operations = [
        migrations.RemoveField(model_name="userprofile", name="crt_enabled"),
        migrations.RemoveField(model_name="userprofile", name="theme"),
    ]
