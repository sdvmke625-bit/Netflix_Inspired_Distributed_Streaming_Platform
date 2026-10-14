"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

django_application = get_asgi_application()

from movies.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        'http': django_application,
        'websocket': URLRouter(websocket_urlpatterns),
    }
)
