"""Internal credential vault API for auto-sign-in consumers."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache

from .models import VaultEntry, log_audit

REVEAL_TTL = 300
REVEAL_PREFIX = "vault:stepup:"


@dataclass
class Credentials:
    username: str
    secret: str
    kind: str
    label: str
    service_id: int | None
    entry_id: int


def list_entries(user):
    return VaultEntry.objects.filter(user=user).select_related("service")


def list_for_service(user, service):
    return list_entries(user).filter(service=service)


def get_credentials(user, service) -> Credentials | None:
    entry = list_for_service(user, service).first()
    if not entry:
        return None
    return _as_credentials(entry)


def get_credentials_by_id(user, entry_id) -> Credentials | None:
    try:
        entry = VaultEntry.objects.get(pk=entry_id, user=user)
    except VaultEntry.DoesNotExist:
        return None
    return _as_credentials(entry)


def _as_credentials(entry: VaultEntry) -> Credentials:
    return Credentials(
        username=entry.username,
        secret=entry.secret_ciphertext or "",
        kind=entry.kind,
        label=entry.label,
        service_id=entry.service_id,
        entry_id=entry.pk,
    )


def serialize_entry(entry: VaultEntry, include_secret=False):
    payload = {
        "id": entry.pk,
        "label": entry.label,
        "username": entry.username,
        "kind": entry.kind,
        "notes": entry.notes,
        "service_id": entry.service_id,
        "service_name": entry.service.name if entry.service_id else "",
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else "",
    }
    if include_secret:
        payload["secret"] = entry.secret_ciphertext or ""
    return payload


def mark_step_up(user, ip=""):
    cache.set(f"{REVEAL_PREFIX}{user.id}", {"ip": ip}, REVEAL_TTL)


def step_up_ok(user) -> bool:
    return cache.get(f"{REVEAL_PREFIX}{user.id}") is not None


def require_step_up(user, password, ip="") -> str:
    if not user.check_password(password or ""):
        return "Invalid password."
    mark_step_up(user, ip)
    return ""


def audit_reveal(request, user, entry: VaultEntry):
    log_audit(
        "vault",
        request=request,
        user=user,
        message=f"Revealed vault entry {entry.label}",
        entry_id=entry.pk,
        service_id=entry.service_id,
    )
