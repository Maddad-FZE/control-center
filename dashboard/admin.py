from django.contrib import admin

from .models import Alert, Bookmark, Service, ServiceCategory, ServiceCheck, ServiceMetric


class ServiceMetricInline(admin.TabularInline):
    model = ServiceMetric
    extra = 0
    fields = ("label", "json_path", "sort_order")


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "layout", "sort_order")
    ordering = ("sort_order",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "widget_type",
        "host",
        "port",
        "is_public",
        "enabled",
        "sort_order",
    )
    list_filter = ("category", "widget_type", "is_public", "enabled")
    search_fields = ("name", "href", "host")
    inlines = [ServiceMetricInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "category",
                    "name",
                    "description",
                    "host",
                    "port",
                    "path",
                    "href",
                    "icon",
                    "logo",
                ),
            },
        ),
        (
            "Health & visibility",
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


@admin.register(ServiceMetric)
class ServiceMetricAdmin(admin.ModelAdmin):
    list_display = ("service", "label", "json_path", "sort_order")
    list_filter = ("service__category",)
    search_fields = ("label", "json_path", "service__name")


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
