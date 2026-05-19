"""
GHAT-GUARDIAN ASGI Configuration
Handles both HTTP (REST API) and WebSocket (live telemetry) traffic.
Django Channels routes WebSocket connections to consumers.py
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import vehicles.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ghat_guardian.settings')

application = ProtocolTypeRouter({
    # Standard HTTP requests (REST API, admin, static files)
    'http': get_asgi_application(),

    # WebSocket connections (live GPS telemetry to dashboard)
    # AuthMiddlewareStack allows session-based auth over WS
    'websocket': AuthMiddlewareStack(
        URLRouter(
            vehicles.routing.websocket_urlpatterns
        )
    ),
})
