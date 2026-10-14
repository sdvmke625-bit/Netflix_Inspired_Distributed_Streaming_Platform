import logging

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import DatabaseError, connection
from django.db.models import F
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from .movie_catalog import get_movie
from .models import Session
from .serializers import SessionSerializer, UserSerializer

logger = logging.getLogger(__name__)


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.exception("Streaming Session health check failed to reach PostgreSQL")
        return JsonResponse({"status": "unhealthy"}, status=503)

    return JsonResponse({"status": "ok"})


@api_view(["POST"])
def user_login(request):
    username = request.data.get("username")
    password = request.data.get("password")
    if not username or not password:
        return Response({"error":"Username and password are required."},status=status.HTTP_400_BAD_REQUEST)
    user = authenticate(
        request,
        username=username,
        password=password,
    )
    if user is None:
        return Response({"error":"Invalid username or password."},status=status.HTTP_401_UNAUTHORIZED)
    refresh = RefreshToken.for_user(user)
    refresh["is_staff"] = user.is_staff
    return Response(
        {
            "message": "Login successful",
            "username": user.username,
            "access": str(refresh.access_token),
        },
        status=status.HTTP_200_OK,
    )
@api_view(["POST"])
def register(request):
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"message":"User created successsfully."},status=status.HTTP_201_CREATED)
    return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def session_list(request):
    if request.method == "GET":
        sessions = Session.objects.filter(user=request.user)
        serializer = SessionSerializer(sessions,many = True)
        return Response(serializer.data)
    if request.method == "POST":
        movie_id = request.data.get("movie_id")
        if movie_id is None:
            return Response(
                {"error": "movie_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        movie = get_movie(movie_id)

        if movie is None:
            return Response(
                {"error": "Movie Catalog Service is unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if movie is False:
            return Response(
                {"error": "Movie not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        movie_duration = movie["duration"]
        serializer = SessionSerializer(
            data=request.data,
            context={"movie_duration": movie_duration},
        )
        if serializer.is_valid():
            serializer.save(user=request.user, movie_duration=movie_duration)
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
        

@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def session_detail(request, pk):
    try:
        session = Session.objects.get(
            pk=pk,
            user=request.user,
        )
    except Session.DoesNotExist:
        return Response({"error" : "Session Not Found"},status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        serializer = SessionSerializer(session)
        return Response(serializer.data)
    if request.method == "PATCH":
        expected_version = request.data.get("version")
        if expected_version is None:
            expected_version = request.data.get("expected_version")

        if expected_version is not None:
            try:
                expected_version = int(expected_version)
            except (TypeError, ValueError):
                return Response(
                    {"error": "Session version must be an integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = SessionSerializer(
            session,
            data={
                key: value for key, value in request.data.items()
                if key not in {"version", "expected_version"}
            },
            partial=True,
        )

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        fields_to_update = {
            key: value
            for key, value in serializer.validated_data.items()
            if key in {"playback_position", "status"}
        }

        if not fields_to_update:
            return Response(SessionSerializer(session).data)

        if expected_version is not None and session.version != expected_version:
            return Response(
                {
                    "error": "Session version conflict",
                    "current_version": session.version,
                    "expected_version": expected_version,
                },
                status=status.HTTP_409_CONFLICT,
            )

        updated = Session.objects.filter(
            pk=session.pk,
            user=request.user,
            version=session.version if expected_version is None else expected_version,
        ).update(
            **fields_to_update,
            version=F("version") + 1,
        )

        if updated == 0:
            current_version = Session.objects.filter(
                pk=session.pk,
                user=request.user,
            ).values_list("version", flat=True).first()
            return Response(
                {
                    "error": "Session version conflict",
                    "current_version": current_version,
                    "expected_version": expected_version if expected_version is not None else session.version,
                },
                status=status.HTTP_409_CONFLICT,
            )

        session.refresh_from_db()
        return Response(SessionSerializer(session).data)
    if request.method == "DELETE":
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
