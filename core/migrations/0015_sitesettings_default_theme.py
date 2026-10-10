from django.db import migrations, models


def seed_default_theme(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("core", "UserProfile")
    site = SiteSettings.objects.filter(pk=1).first()
    if site is None:
        return
    admin = User.objects.filter(is_superuser=True).order_by("id").first()
    if admin is None:
        return
    profile = UserProfile.objects.filter(user_id=admin.pk).first()
    theme = getattr(profile, "theme", "") or ""
    if theme in {"wood", "slate", "terminal"}:
        site.default_theme = theme
        site.save(update_fields=["default_theme"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_users_access_2fa_vault"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="default_theme",
            field=models.CharField(default="wood", max_length=48),
        ),
        migrations.RunPython(seed_default_theme, migrations.RunPython.noop),
    ]
