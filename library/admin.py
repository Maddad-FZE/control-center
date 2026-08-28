from django.contrib import admin

from .models import AddonState, CatalogRelease, InstalledService


@admin.register(AddonState)
class AddonStateAdmin(admin.ModelAdmin):
    list_display = ("slug", "enabled")
    list_filter = ("enabled",)


@admin.register(InstalledService)
class InstalledServiceAdmin(admin.ModelAdmin):
    list_display = ("slug", "status", "managed", "host_port", "installed_version", "installed_at")
    list_filter = ("status",)


@admin.register(CatalogRelease)
class CatalogReleaseAdmin(admin.ModelAdmin):
    list_display = ("repo", "latest_version", "checked_at", "check_error")
    search_fields = ("repo",)
