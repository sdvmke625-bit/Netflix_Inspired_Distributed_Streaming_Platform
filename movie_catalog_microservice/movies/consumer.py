

import json

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from .models import Movie
from .serializers import MovieSerializer


class MovieConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        print("Movie Catalog WebSocket client connected")

    async def receive(self, text_data=None, bytes_data=None):
        print("Received message:", text_data)

        try:
            request = json.loads(text_data)
        except (TypeError, json.JSONDecodeError):
            response = {
                "status": "error",
                "message": "Invalid JSON",
            }
            await self.send(text_data=json.dumps(response))
            return

        if not isinstance(request, dict):
            response = {
                "status": "error",
                "message": "Invalid JSON",
            }
            await self.send(text_data=json.dumps(response))
            return

        operation = request.get("operation")

        if operation == "list_movies":
            response = await self.list_movies(request)
            await self.send(text_data=json.dumps(response))
            return

        if operation == "get_movie":
            response = await self.get_movie(request)
            await self.send(text_data=json.dumps(response))
            return

        response = {
            "status": "error",
            "message": "Unknown operation",
        }
        await self.send(text_data=json.dumps(response))

    @database_sync_to_async
    def list_movies(self, request):
        title = request.get("title", "")
        genre = request.get("genre", "")

        movies = Movie.objects.all().order_by("id")

        if title:
            movies = movies.filter(title__icontains=title)

        if genre:
            movies = movies.filter(genre__icontains=genre)

        serializer = MovieSerializer(movies, many=True)

        return {
            "status": "success",
            "operation": "list_movies",
            "data": serializer.data,
        }

    @database_sync_to_async
    def get_movie(self, request):
        movie_id = request.get("movie_id")

        if movie_id is None:
            return {
                "status": "error",
                "operation": "get_movie",
                "message": "movie_id is required",
            }

        try:
            movie = Movie.objects.get(pk=movie_id)
        except (Movie.DoesNotExist, ValueError, TypeError):
            return {
                "status": "not_found",
                "operation": "get_movie",
                "message": "Movie not found",
            }

        serializer = MovieSerializer(movie)

        return {
            "status": "success",
            "operation": "get_movie",
            "data": serializer.data,
        }

    async def disconnect(self, close_code):
        print("Movie Catalog WebSocket client disconnected")