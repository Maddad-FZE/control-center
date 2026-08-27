from django.contrib import admin
from .models import Alert, Bookmark, Service, ServiceCategory, ServiceCheck


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "layout", "sort_order")
    ordering = ("sort_order",)


class ServiceInline(admin.TabularInline):
    model = Service
    extra = 0
    fields = (
        "name",
        "href",
        "widget_type",
        "widget_url",
        "widget_api_key",
        "enabled",
        "sort_order",
    )


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "widget_type",
        "href",
        "is_public",
        "enabled",
        "sort_order",
    )
    list_filter = ("category", "widget_type", "is_public", "enabled")
    search_fields = ("name", "href")
    fieldsets = (
        (None, {"fields": ("category", "name", "description", "href", "icon")}),
        (
            "Health",
            {"fields": ("health_check_url", "is_public", "enabled", "sort_order")},
        ),
        (
            "Widget",
            {
                "fields": ("widget_type", "widget_url", "widget_api_key"),
                "description": "Homepage-style live stats on the dashboard card.",
            },
        ),
    )


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("name", "href", "sort_order", "enabled")


@admin.register(ServiceCheck)
class ServiceCheckAdmin(admin.ModelAdmin):
    list_display = ("service", "checked_at", "is_up", "response_ms")
    readonly_fields = ("service", "checked_at", "is_up", "response_ms", "error")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "title", "service", "acknowledged")
    list_filter = ("level", "acknowledged")
