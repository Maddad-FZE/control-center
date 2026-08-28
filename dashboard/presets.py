from .forms import WIDGET_PRESETS
from .models import ServiceMetric


def apply_preset_metrics(service, preset):
    if preset == "none" or preset not in WIDGET_PRESETS:
        return
    config = WIDGET_PRESETS[preset]
    service.widget_type = config["widget_type"]
    service.save(update_fields=["widget_type"])
    for idx, (label, path) in enumerate(config["metrics"]):
        ServiceMetric.objects.create(
            service=service,
            label=label,
            json_path=path,
            sort_order=idx,
        )
