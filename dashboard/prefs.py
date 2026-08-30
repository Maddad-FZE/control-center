"""Per-user preference for opening dashboard cards in a new tab."""


def open_in_new_tab_ids(user):
    if not getattr(user, "is_authenticated", False):
        return []
    profile = getattr(user, "profile", None)
    if not profile:
        return []
    ids = profile.open_in_new_tab_ids or []
    result = []
    for value in ids:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def prefers_new_tab(user, service_id):
    return int(service_id) in open_in_new_tab_ids(user)


def set_open_in_new_tab(user, service_id, enabled):
    profile = user.profile
    ids = set(open_in_new_tab_ids(user))
    service_id = int(service_id)
    if enabled:
        ids.add(service_id)
    else:
        ids.discard(service_id)
    profile.open_in_new_tab_ids = sorted(ids)
    profile.save(update_fields=["open_in_new_tab_ids"])
    return enabled
