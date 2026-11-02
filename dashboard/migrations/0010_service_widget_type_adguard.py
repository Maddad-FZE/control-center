from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0009_debugincident"),
    ]

    operations = [
        migrations.AlterField(
            model_name="service",
            name="widget_type",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("pihole", "Pi-hole"),
                    ("speedtest", "Speedtest Tracker"),
                    ("adguard", "AdGuard Home"),
                ],
                default="none",
                max_length=16,
            ),
        ),
    ]
