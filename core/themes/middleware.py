"""Bind the resolved theme to the request via a contextvar."""

import contextvars

from core.themes.registry import resolve_theme

_active = contextvars.ContextVar("cc_active_theme", default=None)


def get_active_theme():
    theme = _active.get()
    if theme is None:
        return resolve_theme(None)
    return theme


def set_active_theme(theme):
    """Return the reset token. Tests and the middleware use this."""
    return _active.set(theme)


def reset_active_theme(token):
    _active.reset(token)


class ThemeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        theme = resolve_theme(request)
        request.theme = theme
        token = set_active_theme(theme)
        try:
            return self.get_response(request)
        finally:
            reset_active_theme(token)
