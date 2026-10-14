import json

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from django.db.models import F

from .models import Session
from .serializers import SessionSerializer
from .movie_catalog import get_movie

User = get_user_model()


class SessionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = None
        self.is_authenticated = False
        await self.accept()
        print("Streaming Session WebSocket client connected")

    async def disconnect(self, close_code):
        self.user = None
        self.is_authenticated = False
        print("Streaming Session WebSocket client disconnected")

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

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

        if operation == "authenticate":
            access_token = request.get("token")

            if not access_token:
                response = {
                    "status": "error",
                    "operation": "authenticate",
                    "message": "Access token is required",
                }
                await self.send(text_data=json.dumps(response))
                return

            try:
                token = AccessToken(access_token)
                user_id = token["user_id"]
                user = await self.get_user(user_id)
                if user is None:
                    raise ValueError("User not found")
                self.user = user
                self.is_authenticated = True
            except Exception:
                self.user = None
                self.is_authenticated = False
                response = {
                    "status": "error",
                    "operation": "authenticate",
                    "message": "Invalid or expired access token",
                }
                await self.send(text_data=json.dumps(response))
                return

            response = {
                "status": "success",
                "operation": "authenticate",
                "data": {
                    "user_id": self.user.id,
                    "username": self.user.username,
                },
            }
            await self.send(text_data=json.dumps(response))
            print("WebSocket user authenticated:", self.user.username)
            return

        if not self.is_authenticated or self.user is None:
            response = {
                "status": "error",
                "message": "Authentication required",
            }
            await self.send(text_data=json.dumps(response))
            return

        if operation == "list_sessions":
            response = await self.handle_list_sessions()
            await self.send(text_data=json.dumps(response))
            print("operation completed: list_sessions")
            return

        if operation == "create_session":
            response = await self.handle_create_session(request)
            await self.send(text_data=json.dumps(response))
            print("operation completed: create_session")
            return

        if operation == "update_session":
            response = await self.handle_update_session(request)
            await self.send(text_data=json.dumps(response))
            print("operation completed: update_session")
            return

        response = {
            "status": "error",
            "message": "Unknown operation",
        }
        await self.send(text_data=json.dumps(response))

    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def handle_list_sessions(self):
        sessions = Session.objects.filter(user=self.user)
        serializer = SessionSerializer(sessions, many=True)
        return {
            "status": "success",
            "operation": "list_sessions",
            "data": serializer.data,
        }

    @database_sync_to_async
    def handle_create_session(self, request):
        movie_id = request.get("movie_id")
        if movie_id is None:
            return {
                "status": "error",
                "operation": "create_session",
                "message": "movie_id is required",
            }

        movie = get_movie(movie_id)

        if movie is None:
            return {
                "status": "error",
                "operation": "create_session",
                "message": "Movie Catalog Service is unavailable.",
            }

        if movie is False:
            return {
                "status": "error",
                "operation": "create_session",
                "message": "Movie not found",
            }

        movie_duration = movie.get("duration")
        if movie_duration is None:
            return {
                "status": "error",
                "operation": "create_session",
                "message": "Movie duration missing from Movie Catalog.",
            }

        session_data = {
            k: v for k, v in request.items()
            if k not in ("operation",)
        }

        serializer = SessionSerializer(
            data=session_data,
            context={"movie_duration": movie_duration},
        )

        if serializer.is_valid():
            serializer.save(user=self.user, movie_duration=movie_duration)
            return {
                "status": "success",
                "operation": "create_session",
                "data": serializer.data,
            }

        first_field, first_error = next(iter(serializer.errors.items()))
        msg = first_error[0] if isinstance(first_error, list) and first_error else str(first_error)
        err_msg = f"{first_field}: {msg}" if first_field != "non_field_errors" else str(msg)

        return {
            "status": "error",
            "operation": "create_session",
            "message": err_msg,
            "errors": serializer.errors,
        }

    @database_sync_to_async
    def handle_update_session(self, request):
        session_id = request.get("session_id")
        if session_id is None:
            return {
                "status": "error",
                "operation": "update_session",
                "message": "session_id is required",
            }

        try:
            session = Session.objects.get(
                pk=session_id,
                user=self.user,
            )
        except (Session.DoesNotExist, ValueError):
            return {
                "status": "error",
                "operation": "update_session",
                "message": "Session not found",
            }

        update_data = {
            k: v for k, v in request.items()
            if k not in ("operation", "session_id", "version", "expected_version")
        }

        expected_version_raw = request.get("version")
        if expected_version_raw is None:
            expected_version_raw = request.get("expected_version")

        if expected_version_raw is not None:
            try:
                expected_version = int(expected_version_raw)
            except (TypeError, ValueError):
                return {
                    "status": "error",
                    "operation": "update_session",
                    "message": "Session version must be an integer",
                }
        else:
            expected_version = None

        if (
            session.status == "ended"
            and session.playback_position == session.movie_duration
            and update_data
            and set(update_data).issubset({"playback_position", "status"})
            and update_data.get("playback_position", session.playback_position)
            == session.movie_duration
            and update_data.get("status", "ended") == "ended"
        ):
            return {
                "status": "success",
                "operation": "update_session",
                "data": SessionSerializer(session).data,
            }

        serializer = SessionSerializer(
            session,
            data=update_data,
            partial=True,
        )

        if not serializer.is_valid():
            first_field, first_error = next(iter(serializer.errors.items()))
            msg = first_error[0] if isinstance(first_error, list) and first_error else str(first_error)
            err_msg = f"{first_field}: {msg}" if first_field != "non_field_errors" else str(msg)
            return {
                "status": "error",
                "operation": "update_session",
                "message": err_msg,
                "errors": serializer.errors,
            }

        fields_to_update = {
            key: value
            for key, value in serializer.validated_data.items()
            if key in {"playback_position", "status"}
        }

        if not fields_to_update:
            return {
                "status": "success",
                "operation": "update_session",
                "data": SessionSerializer(session).data,
            }

        lock_version = session.version if expected_version is None else expected_version
        if expected_version is not None and session.version != expected_version:
            return {
                "status": "error",
                "operation": "update_session",
                "message": "Session version conflict",
                "data": {
                    "current_version": session.version,
                    "expected_version": expected_version,
                },
            }

        updated_rows = Session.objects.filter(
            pk=session.pk,
            user=self.user,
            version=lock_version,
        ).update(
            **fields_to_update,
            version=F("version") + 1,
        )

        if updated_rows == 0:
            current_version = Session.objects.filter(
                pk=session.pk,
                user=self.user,
            ).values_list("version", flat=True).first()
            if current_version is None:
                return {
                    "status": "error",
                    "operation": "update_session",
                    "message": "Session not found",
                }
            return {
                "status": "error",
                "operation": "update_session",
                "message": "Session version conflict",
                "data": {
                    "current_version": current_version,
                    "expected_version": expected_version if expected_version is not None else session.version,
                },
            }

        session.refresh_from_db()
        return {
            "status": "success",
            "operation": "update_session",
            "data": SessionSerializer(session).data,
        }


TestConsumer = SessionConsumer
