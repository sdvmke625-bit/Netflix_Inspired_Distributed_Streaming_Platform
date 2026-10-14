

from django.urls import re_path

from .consumer import MovieConsumer


websocket_urlpatterns = [
    re_path(r"ws/movies/$", MovieConsumer.as_asgi()),
]