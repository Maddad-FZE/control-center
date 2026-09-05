"""Settings → Users JSON helpers."""

from __future__ import annotations

import secrets

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from dashboard.models import Service

from .access import ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER, role_of
from .models import UserProfile, log_audit
from .totp import clear_twofa, twofa_enabled

ROLES = {ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER}


def serialize_user(user, request_user=None):
    profile = getattr(user, "profile", None)
    role = role_of(user)
    allowed = []
    if profile:
        allowed = list(profile.allowed_services.values_list("id", flat=True))
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": role,
        "is_active": user.is_active,
        "last_login": user.last_login.strftime("%Y-%m-%d %H:%M") if user.last_login else "",
        "twofa_enabled": twofa_enabled(user),
        "must_change_password": bool(profile and profile.must_change_password),
        "allowed_service_ids": allowed,
        "is_self": bool(request_user and request_user.id == user.id),
    }


def list_users(request_user):
    rows = User.objects.order_by("username").select_related("profile").prefetch_related(
        "profile__allowed_services"
    )
    return [serialize_user(u, request_user) for u in rows]


def enabled_services():
    return list(Service.objects.filter(enabled=True).order_by("name").values("id", "name"))


def _apply_role(user, role):
    if role not in ROLES:
        raise ValidationError("Invalid role.")
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    if role == ROLE_ADMIN:
        user.is_superuser = True
        user.is_staff = True
    else:
        user.is_superuser = False
        user.is_staff = False
    profile.save()
    user.save(update_fields=["is_superuser", "is_staff", "is_active", "email", "first_name", "last_name"])


def active_admin_count():
    return User.objects.filter(is_active=True, is_superuser=True).count()


def _guard_last_admin(user, *, making_inactive=False, demoting=False):
    if not user.is_superuser:
        return
    if making_inactive or demoting:
        others = User.objects.filter(is_active=True, is_superuser=True).exclude(pk=user.pk)
        if not others.exists():
            raise ValidationError("Cannot remove the last active admin.")


def create_user(actor, data, request=None):
    username = (data.get("username") or "").strip()
    if not username:
        raise ValidationError("Username is required.")
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError("That username is already taken.")
    role = (data.get("role") or ROLE_MEMBER).strip()
    if role not in ROLES:
        raise ValidationError("Invalid role.")
    password = data.get("password") or ""
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True
    try:
        validate_password(password)
    except ValidationError as exc:
        raise ValidationError(" ".join(exc.messages))
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=(data.get("email") or "").strip(),
            password=password,
            first_name=(data.get("first_name") or "").strip(),
            last_name=(data.get("last_name") or "").strip(),
        )
        user.is_active = bool(data.get("is_active", True))
        _apply_role(user, role)
        profile = user.profile
        profile.must_change_password = bool(data.get("must_change_password", generated))
        profile.save(update_fields=["must_change_password", "role"])
        _set_allowed(profile, role, data.get("allowed_service_ids") or [])
    log_audit("user", request=request, user=actor, message=f"Created user {user.username}", target=user.username)
    result = serialize_user(user, actor)
    if generated:
        result["generated_password"] = password
    return result


def update_user(actor, user, data, request=None):
    if "username" in data:
        username = (data.get("username") or "").strip()
        if username and username != user.username:
            if User.objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
                raise ValidationError("That username is already taken.")
            user.username = username
    if "email" in data:
        user.email = (data.get("email") or "").strip()
    if "first_name" in data:
        user.first_name = (data.get("first_name") or "").strip()
    if "last_name" in data:
        user.last_name = (data.get("last_name") or "").strip()
    role = data.get("role")
    making_inactive = "is_active" in data and not bool(data.get("is_active"))
    demoting = role in ROLES and role != ROLE_ADMIN and user.is_superuser
    _guard_last_admin(user, making_inactive=making_inactive, demoting=demoting)
    if "is_active" in data:
        user.is_active = bool(data.get("is_active"))
    with transaction.atomic():
        if role:
            _apply_role(user, role)
        else:
            user.save()
        profile = user.profile
        if "must_change_password" in data:
            profile.must_change_password = bool(data.get("must_change_password"))
            profile.save(update_fields=["must_change_password"])
        if "allowed_service_ids" in data:
            _set_allowed(profile, role_of(user), data.get("allowed_service_ids") or [])
    log_audit("user", request=request, user=actor, message=f"Updated user {user.username}", target=user.username)
    return serialize_user(user, actor)


def _set_allowed(profile, role, service_ids):
    if role == ROLE_ADMIN:
        profile.allowed_services.clear()
        return
    ids = []
    for item in service_ids:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    profile.allowed_services.set(Service.objects.filter(pk__in=ids, enabled=True))


def set_password(actor, user, password, request=None, generate=False):
    generated = ""
    if generate or not password:
        generated = secrets.token_urlsafe(12)
        password = generated
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise ValidationError(" ".join(exc.messages))
    user.set_password(password)
    user.save(update_fields=["password"])
    profile = user.profile
    profile.must_change_password = True
    profile.save(update_fields=["must_change_password"])
    log_audit("user", request=request, user=actor, message=f"Reset password for {user.username}", target=user.username)
    payload = serialize_user(user, actor)
    if generated:
        payload["generated_password"] = generated
    return payload


def delete_user(actor, user, confirm_username, request=None):
    if actor.id == user.id:
        raise ValidationError("You cannot delete your own account.")
    if (confirm_username or "").strip() != user.username:
        raise ValidationError("Type the username to confirm deletion.")
    _guard_last_admin(user, making_inactive=True, demoting=True)
    username = user.username
    user.delete()
    log_audit("user", request=request, user=actor, message=f"Deleted user {username}", target=username)


def reset_twofa(actor, user, request=None):
    clear_twofa(user)
    log_audit("2fa", request=request, user=actor, message=f"Reset 2FA for {user.username}", target=user.username)
    return serialize_user(user, actor)
