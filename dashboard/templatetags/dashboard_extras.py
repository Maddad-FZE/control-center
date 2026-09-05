from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    return mapping.get(key)


@register.filter
def service_is_down(status_row):
    """True only when a health check explicitly reported down (not unknown)."""
    if not status_row:
        return False
    return status_row.get("is_up") is False
