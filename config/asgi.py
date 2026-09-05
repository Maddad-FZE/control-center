"""
ASGI config for Control Center — Django HTTP + console WebSocket.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()


async def application(scope, receive, send):
    if scope["type"] == "websocket" and scope.get("path") == "/ws/console/":
        from core.console import websocket_console

        await websocket_console(scope, receive, send)
        return
    await django_asgi_app(scope, receive, send)
