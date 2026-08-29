from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import AuditEvent, SiteSettings, UpdateStatus, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("title", "tagline", "weather_location", "wizard_enabled")


@admin.register(UpdateStatus)
class UpdateStatusAdmin(admin.ModelAdmin):
    list_display = ("latest_version", "last_checked_at", "install_state")
    readonly_fields = ("last_checked_at", "install_started_at", "install_finished_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "username", "ip_address", "message")
    list_filter = ("event_type",)
    search_fields = ("username", "message")
    readonly_fields = ("created_at", "event_type", "user", "username", "ip_address", "message", "metadata")
