from django import forms
from urllib.parse import urlparse

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


class ServiceForm(forms.ModelForm):
    preset = forms.ChoiceField(
        choices=[
            ("none", "None — custom metrics only"),
            ("pihole", "Pi-hole preset"),
            ("speedtest", "Speedtest preset"),
        ],
        required=False,
        initial="none",
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
            "enabled",
            "widget_type",
            "widget_url",
            "widget_api_key",
            "catalog_slug",
            "check_updates",
            "sort_order",
        )
        widgets = {
            "description": forms.TextInput(attrs={"placeholder": "Short title / subtitle"}),
            "host": forms.TextInput(attrs={"placeholder": "192.168.0.40"}),
            "port": forms.NumberInput(attrs={"placeholder": "8080"}),
            "path": forms.TextInput(attrs={"placeholder": "/"}),
            "widget_url": forms.URLInput(attrs={"placeholder": "http://host:port"}),
            "catalog_slug": forms.HiddenInput(),
        }

    def clean(self):
        cleaned = super().clean()
        host = cleaned.get("host")
        port = cleaned.get("port")
        widget_url = cleaned.get("widget_url") or ""
        if widget_url and (not host or not port):
            parsed = urlparse(widget_url)
            if not host and parsed.hostname:
                cleaned["host"] = parsed.hostname
            if not port and parsed.port:
                cleaned["port"] = parsed.port
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.widget_type == Service.WidgetType.PIHOLE:
                self.fields["preset"].initial = "pihole"
            elif self.instance.widget_type == Service.WidgetType.SPEEDTEST:
                self.fields["preset"].initial = "speedtest"


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
    extra=3,
    can_delete=True,
)
