from urllib.parse import urlparse

from django import forms

from library.catalog import LIBRARY_DESCRIPTIONS, SERVICES, get_service_by_slug
from library.icons import icon_url_for_entry
from library.models import InstalledService

from .icon_library import icon_url, slug_from_icon_url
from .models import Service, ServiceCategory, ServiceMetric

WIDGET_PRESETS = {
    "pihole": {
        "widget_type": Service.WidgetType.PIHOLE,
        "metrics": [
            ("QUERIES", "queries.total"),
            ("BLOCKED", "queries.blocked"),
            ("GRAVITY", "gravity.domains_being_blocked"),
        ],
    },
    "speedtest": {
        "widget_type": Service.WidgetType.SPEEDTEST,
        "metrics": [
            ("DOWNLOAD", "download"),
            ("UPLOAD", "upload"),
            ("PING", "ping"),
        ],
    },
}

LINK_CUSTOM = "__custom__"


def _ensure_category(name):
    if not name:
        return None
    cat, _ = ServiceCategory.objects.get_or_create(
        name=name,
        defaults={"sort_order": 50},
    )
    return cat


def link_choice_groups():
    """Return (choices, meta) for the named service picker."""
    by_slug = {entry["slug"]: entry for entry in SERVICES}
    installed = list(
        InstalledService.objects.filter(status__in=("running", "stopped", "installing"))
    )
    installed_slugs = {row.slug for row in installed}

    groups = []
    meta = {}

    installed_choices = []
    for row in installed:
        entry = by_slug.get(row.slug, {})
        name = entry.get("name") or row.slug
        key = f"installed:{row.slug}"
        installed_choices.append((key, name))
        meta[key] = _meta_for_entry(entry, row)
    if installed_choices:
        groups.append(("Installed", installed_choices))

    library_choices = []
    for entry in SERVICES:
        if entry["slug"] in installed_slugs:
            continue
        key = f"catalog:{entry['slug']}"
        library_choices.append((key, entry["name"]))
        meta[key] = _meta_for_entry(entry, None)
    if library_choices:
        groups.append(("Library", library_choices))

    groups.append(("Other", [(LINK_CUSTOM, "Custom link…")]))
    meta[LINK_CUSTOM] = {"custom": True}
    return groups, meta


def _meta_for_entry(entry, installed):
    slug = (entry or {}).get("slug") or (installed.slug if installed else "")
    category = _ensure_category((entry or {}).get("category"))
    widget = (entry or {}).get("widget_type", "none")
    preset = "none"
    if widget == "pihole":
        preset = "pihole"
    elif widget == "speedtest":
        preset = "speedtest"
    port = 0
    if installed and installed.host_port:
        port = installed.host_port
    elif entry:
        port = entry.get("default_port") or 0
    return {
        "custom": False,
        "slug": slug,
        "name": (entry or {}).get("name") or slug,
        "description": LIBRARY_DESCRIPTIONS.get(slug) or (entry or {}).get("tagline", ""),
        "icon": icon_url_for_entry(slug, (entry or {}).get("icon", "")),
        "category_id": category.id if category else "",
        "path": (entry or {}).get("path", "/") or "/",
        "port": port,
        "preset": preset,
        "widget_type": widget,
    }


class ServiceForm(forms.ModelForm):
    linked_service = forms.ChoiceField(
        label="Service",
        required=True,
        help_text="Pick by name. The host is set automatically.",
    )
    open_url = forms.URLField(
        label="Link",
        required=False,
        help_text="Full URL for a custom card (router, cloud app, etc.).",
    )
    icon_slug = forms.CharField(required=False, widget=forms.HiddenInput())
    preset = forms.ChoiceField(
        choices=[
            ("none", "None"),
            ("pihole", "Pi-hole"),
            ("speedtest", "Speedtest"),
            ("custom", "Custom metrics"),
        ],
        required=False,
        initial="none",
        label="Live stats",
    )

    class Meta:
        model = Service
        fields = (
            "category",
            "name",
            "description",
            "host",
            "port",
            "path",
            "logo",
            "icon",
            "health_check_url",
            "is_public",
            "is_misc",
            "enabled",
            "widget_type",
            "widget_url",
            "widget_api_key",
            "catalog_slug",
            "check_updates",
            "sort_order",
        )
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": "What this app does"}
            ),
            "catalog_slug": forms.HiddenInput(),
            "host": forms.HiddenInput(),
            "port": forms.HiddenInput(),
            "path": forms.HiddenInput(),
            "icon": forms.HiddenInput(),
            "widget_url": forms.HiddenInput(),
            "widget_type": forms.HiddenInput(),
            "health_check_url": forms.HiddenInput(),
            "sort_order": forms.HiddenInput(),
        }

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        groups, self.link_meta = link_choice_groups()
        self.fields["linked_service"].choices = groups
        self.fields["linked_service"].widget.attrs["id"] = "id_linked_service"
        self.fields["name"].required = True
        self.fields["enabled"].initial = True
        self.fields["logo"].label = "Or upload a logo"
        self.fields["widget_api_key"].label = "API key"
        self.fields["is_misc"].label = "Show in Misc"
        self.fields["is_public"].label = "Visible to guests"
        self.fields["open_url"].widget.attrs.setdefault("placeholder", "http://192.168.0.1/")
        for name in (
            "widget_type",
            "host",
            "port",
            "path",
            "icon",
            "widget_url",
            "health_check_url",
            "catalog_slug",
            "sort_order",
        ):
            self.fields[name].required = False

        instance = self.instance
        if instance and instance.pk:
            slug = instance.catalog_slug
            if slug and f"installed:{slug}" in self.link_meta:
                self.initial.setdefault("linked_service", f"installed:{slug}")
            elif slug and f"catalog:{slug}" in self.link_meta:
                self.initial.setdefault("linked_service", f"catalog:{slug}")
            else:
                self.initial.setdefault("linked_service", LINK_CUSTOM)
                self.initial.setdefault("open_url", instance.href)
            self.initial.setdefault("icon_slug", slug_from_icon_url(instance.icon))
            if instance.widget_type == Service.WidgetType.PIHOLE:
                self.fields["preset"].initial = "pihole"
            elif instance.widget_type == Service.WidgetType.SPEEDTEST:
                self.fields["preset"].initial = "speedtest"
            elif instance.metrics.exists() or instance.widget_type != Service.WidgetType.NONE:
                self.fields["preset"].initial = "custom"
        elif self.initial.get("catalog_slug"):
            slug = self.initial["catalog_slug"]
            if f"installed:{slug}" in self.link_meta:
                self.initial.setdefault("linked_service", f"installed:{slug}")
            else:
                self.initial.setdefault("linked_service", f"catalog:{slug}")
            self.initial.setdefault("icon_slug", slug_from_icon_url(self.initial.get("icon", "")))

        if not self.initial.get("linked_service"):
            self.initial["linked_service"] = LINK_CUSTOM

    def clean(self):
        cleaned = super().clean()
        from library.installer import services_host

        key = cleaned.get("linked_service") or LINK_CUSTOM
        host = services_host(self.request)
        icon_slug = (cleaned.get("icon_slug") or "").strip()
        if icon_slug:
            cleaned["icon"] = icon_url(icon_slug)

        if key == LINK_CUSTOM:
            url = (cleaned.get("open_url") or "").strip()
            if not url:
                self.add_error("open_url", "Enter a link for a custom card.")
                return cleaned
            parsed = urlparse(url)
            if not parsed.hostname:
                self.add_error("open_url", "Enter a full URL including http://")
                return cleaned
            cleaned["host"] = parsed.hostname
            cleaned["port"] = parsed.port or (443 if parsed.scheme == "https" else 80)
            cleaned["path"] = parsed.path or "/"
            cleaned["catalog_slug"] = ""
            if not cleaned.get("health_check_url"):
                cleaned["health_check_url"] = url
        else:
            _kind, slug = key.split(":", 1)
            entry = get_service_by_slug(slug) or {}
            meta = self.link_meta.get(key) or _meta_for_entry(entry, None)
            cleaned["catalog_slug"] = slug
            cleaned["host"] = host
            cleaned["port"] = meta.get("port") or entry.get("default_port") or None
            cleaned["path"] = meta.get("path") or entry.get("path") or "/"
            if not cleaned.get("name"):
                cleaned["name"] = meta.get("name") or entry.get("name") or slug
            if not cleaned.get("description"):
                cleaned["description"] = meta.get("description") or ""
            if not cleaned.get("icon"):
                cleaned["icon"] = meta.get("icon") or icon_url_for_entry(slug, entry.get("icon", ""))
            if not cleaned.get("category") and meta.get("category_id"):
                cleaned["category"] = ServiceCategory.objects.filter(pk=meta["category_id"]).first()
            if cleaned.get("port"):
                cleaned["widget_url"] = f"http://{host}:{cleaned['port']}"
                if not cleaned.get("health_check_url"):
                    path = cleaned["path"] or "/"
                    cleaned["health_check_url"] = f"http://{host}:{cleaned['port']}{path}"

        preset = cleaned.get("preset") or "none"
        if preset == "pihole":
            cleaned["widget_type"] = Service.WidgetType.PIHOLE
        elif preset == "speedtest":
            cleaned["widget_type"] = Service.WidgetType.SPEEDTEST
        elif preset == "custom":
            if not cleaned.get("widget_type"):
                cleaned["widget_type"] = Service.WidgetType.NONE
        else:
            cleaned["widget_type"] = Service.WidgetType.NONE
            cleaned["widget_api_key"] = cleaned.get("widget_api_key") or ""

        if cleaned.get("host") and cleaned.get("port") and not cleaned.get("widget_url"):
            cleaned["widget_url"] = f"http://{cleaned['host']}:{cleaned['port']}"
        return cleaned


class ServiceMetricForm(forms.ModelForm):
    class Meta:
        model = ServiceMetric
        fields = ("label", "json_path", "sort_order")
        widgets = {
            "label": forms.TextInput(attrs={"placeholder": "QUERIES"}),
            "json_path": forms.TextInput(attrs={"placeholder": "queries.total"}),
            "sort_order": forms.HiddenInput(),
        }


ServiceMetricFormSet = forms.inlineformset_factory(
    Service,
    ServiceMetric,
    form=ServiceMetricForm,
    extra=1,
    can_delete=True,
)
