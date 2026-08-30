from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_sitesettings_kuma"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="cf_api_token",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="cf_account_id",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="cf_zone_id",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="cf_zone_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="cf_tunnel_id",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="cf_tunnel_token",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="cf_tunnel_name",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
