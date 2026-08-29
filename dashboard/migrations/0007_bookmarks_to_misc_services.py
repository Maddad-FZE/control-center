from django.db import migrations, models


def bookmarks_to_services(apps, schema_editor):
    Bookmark = apps.get_model("dashboard", "Bookmark")
    Service = apps.get_model("dashboard", "Service")
    ServiceCategory = apps.get_model("dashboard", "ServiceCategory")

    tools, _ = ServiceCategory.objects.get_or_create(
        name="Tools",
        defaults={"sort_order": 2, "layout": "grid"},
    )

    existing_names = {name.lower() for name in Service.objects.values_list("name", flat=True)}
    existing_hrefs = {
        href.rstrip("/") for href in Service.objects.values_list("href", flat=True) if href
    }

    for bookmark in Bookmark.objects.filter(enabled=True).order_by("sort_order", "name"):
        href = (bookmark.href or "").rstrip("/")
        if bookmark.name.lower() in existing_names or (href and href in existing_hrefs):
            continue
        Service.objects.create(
            category=tools,
            name=bookmark.name,
            description="",
            href=bookmark.href,
            icon=bookmark.icon or "",
            health_check_url=bookmark.href,
            is_public=False,
            is_misc=True,
            sort_order=100 + bookmark.sort_order,
            enabled=True,
        )
        existing_names.add(bookmark.name.lower())
        if href:
            existing_hrefs.add(href)

    Bookmark.objects.all().delete()


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0006_service_is_misc"),
    ]

    operations = [
        migrations.RunPython(bookmarks_to_services, noop_reverse),
        migrations.AlterField(
            model_name="service",
            name="is_misc",
            field=models.BooleanField(
                default=False,
                help_text="Show this card in Misc instead of Apps or Tracked",
            ),
        ),
    ]
