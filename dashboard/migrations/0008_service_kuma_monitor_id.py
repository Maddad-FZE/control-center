from django.db import migrations, models


def mark_kuma_misc(apps, schema_editor):
    Service = apps.get_model("dashboard", "Service")
    Service.objects.filter(catalog_slug="uptime-kuma").update(is_misc=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0007_bookmarks_to_misc_services"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="kuma_monitor_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(mark_kuma_misc, noop),
    ]
