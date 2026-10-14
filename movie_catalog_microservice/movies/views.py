import logging
import os

from django.db import DatabaseError, connection
from django.http import JsonResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTStatelessUserAuthentication


from .models import Movie
from .permissions import IsCatalogWriterOrReadOnly
from .serializers import MovieSerializer

logger = logging.getLogger(__name__)


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.exception("Movie Catalog health check failed to reach PostgreSQL")
        return JsonResponse({"status": "unhealthy"}, status=503)

    return JsonResponse({
        "status": "ok",
        "instance": os.environ.get("HOSTNAME", "movie_catalog"),
    })


@api_view(["GET", "POST"])
@authentication_classes([JWTStatelessUserAuthentication])
@permission_classes([IsCatalogWriterOrReadOnly])
def movie_list(request):
    if request.method == "GET":
        genre = request.query_params.get("genre")
        title = request.query_params.get("title")
        movies = Movie.objects.all()
        if genre:
            movies = movies.filter(genre__iexact=genre)
        if title:
            movies = movies.filter(title__icontains=title)
        serializer = MovieSerializer(movies, many=True)
        return Response(serializer.data)
    if request.method == "POST":
        title = request.data.get("title")
        if title is not None:
            title = title.strip()
            if Movie.objects.filter(title__iexact=title).exists():
                return Response(
                    {"error": "A movie with this title already exists."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        serializer = MovieSerializer(data = request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)

    
@api_view(["GET","PUT","DELETE"])
@authentication_classes([JWTStatelessUserAuthentication])
@permission_classes([IsCatalogWriterOrReadOnly])
def movie_detail(request,pk):
    try:
        movie = Movie.objects.get(pk=pk)
    except Movie.DoesNotExist:
        return Response({
            "error" : "Movie not found"
        },status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        serializer = MovieSerializer(movie)
        return Response(serializer.data)
    if request.method == "PUT":
        title = request.data.get("title")
        if title is not None:
            title = title.strip()
            if Movie.objects.filter(title__iexact=title).exclude(pk=movie.pk).exists():
                return Response(
                    {"error": "A movie with this title already exists."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        serializer = MovieSerializer(movie,data = request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
    if request.method == "DELETE":
        movie.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    







    
