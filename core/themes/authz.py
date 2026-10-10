"""Who may change or preview the site theme."""


def can_manage_theme(user) -> bool:
    """Superusers only. Matches the gate on Settings views."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_superuser", False)
    )
