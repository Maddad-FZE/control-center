"""Role and per-service access helpers."""

from django.contrib.auth.models import AnonymousUser

from dashboard.models import Service

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"


def _profile(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "profile", None)


def role_of(user) -> str:
    if not user or isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        return ""
    if user.is_superuser:
        return ROLE_ADMIN
    profile = _profile(user)
    if profile and profile.role:
        return profile.role
    return ROLE_MEMBER


def is_admin(user) -> bool:
    return role_of(user) == ROLE_ADMIN


def can_manage_users(user) -> bool:
    return is_admin(user)


def is_viewer(user) -> bool:
    return role_of(user) == ROLE_VIEWER


def visible_service_ids(user):
    qs = Service.objects.filter(enabled=True)
    if not user or not getattr(user, "is_authenticated", False):
        return set(qs.filter(is_public=True).values_list("id", flat=True))
    if is_admin(user):
        return set(qs.values_list("id", flat=True))
    public_ids = set(qs.filter(is_public=True).values_list("id", flat=True))
    profile = _profile(user)
    allowed = set()
    if profile:
        allowed = set(profile.allowed_services.filter(enabled=True).values_list("id", flat=True))
    return public_ids | allowed


def visible_services_for(user):
    ids = visible_service_ids(user)
    return Service.objects.filter(id__in=ids, enabled=True)


def can_open_service(user, service) -> bool:
    if not service or not service.enabled:
        return False
    return service.id in visible_service_ids(user)


def can_act_on_service(user, service) -> bool:
    if is_viewer(user):
        return False
    return can_open_service(user, service)


def can_ack_alerts(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return not is_viewer(user)
