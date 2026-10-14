import os
import socket
import json
import logging
import sys
import threading

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.db import DatabaseError, connection

from movies.models import Movie
from movies.serializers import MovieSerializer


HOST = os.environ.get("MOVIE_CATALOG_TCP_BIND_HOST", "0.0.0.0")
PORT = int(os.environ.get("MOVIE_CATALOG_TCP_PORT", "9002"))
CONNECTION_TIMEOUT_SECONDS = float(
    os.environ.get("MOVIE_CATALOG_TCP_TIMEOUT_SECONDS", "2")
)
MAX_REQUEST_BYTES = 64 * 1024
MAX_CONCURRENT_CONNECTIONS = 64
logger = logging.getLogger(__name__)


def read_request(connection):
    chunks = []
    size = 0

    while True:
        chunk = connection.recv(min(4096, MAX_REQUEST_BYTES + 1 - size))
        if not chunk:
            # HAProxy and the container health check open a TCP connection to
            # verify reachability, then close it without sending a frame.
            # Treat that as a probe instead of a malformed client request.
            if size == 0:
                raise EOFError("Connection closed without a request")
            raise ValueError("Request must end with a newline")

        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise ValueError("Request is too large")

        chunks.append(chunk)
        if b"\n" in chunk:
            break

    data = b"".join(chunks)
    if b"\n" not in data:
        raise ValueError("Request must end with a newline")
    payload = data.split(b"\n", 1)[0].strip()
    if not payload:
        raise ValueError("Request is empty")

    request = json.loads(payload.decode("utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Request must be a JSON object")
    return request


def handle_connection(connection, address):
    with connection:
        connection.settimeout(CONNECTION_TIMEOUT_SECONDS)
        try:
            request = read_request(connection)
            response = handle_request(request)
        except EOFError:
            # A TCP reachability check does not send an application frame.
            # Closing quietly avoids warning noise for expected health probes.
            return
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = {"status": "error", "message": "Invalid JSON"}
        except (OSError, ValueError) as exc:
            logger.warning("Invalid TCP request from %s: %s", address, exc)
            response = {"status": "error", "message": str(exc)}
        except Exception:
            # A request-specific database/serialization failure must not kill the
            # worker or leave a client waiting for a response.
            logger.exception("Movie Catalog TCP request failed for %s", address)
            response = {"status": "error", "message": "Internal server error"}

        try:
            connection.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except OSError:
            logger.warning("Could not send TCP response to %s", address)


def handle_request(request):
    if request.get("operation") == "health":
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            logger.exception("Movie Catalog TCP health check failed")
            return {"status": "error", "message": "Database unavailable"}
        return {"status": "success", "operation": "health"}

    if request.get("operation") != "get_movie":
        return {
            "status": "error",
            "message": "Invalid request",
        }

    movie_id = request.get("movie_id")

    if movie_id is None:
        return {
            "status": "error",
            "message": "movie_id is required",
        }

    try:
        movie = Movie.objects.get(pk=movie_id)
    except (Movie.DoesNotExist, ValueError, TypeError):
        return {
            "status": "not_found",
            "message": "Movie not found",
        }

    serializer = MovieSerializer(movie)

    return {
        "status": "success",
        "movie": serializer.data,
    }


def run_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection_slots = threading.BoundedSemaphore(MAX_CONCURRENT_CONNECTIONS)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen()

    print(f"Movie Catalog TCP server listening on {HOST}:{PORT}")

    try:
        while True:
            connection, address = server_socket.accept()
            if not connection_slots.acquire(blocking=False):
                with connection:
                    try:
                        connection.sendall(
                            b'{"status":"error","message":"Server is busy"}\n'
                        )
                    except OSError:
                        logger.warning("Could not send overload response to %s", address)
                continue
            threading.Thread(
                target=_handle_connection,
                args=(connection, address, connection_slots),
                daemon=True,
            ).start()
    finally:
        server_socket.close()


def _handle_connection(connection, address, connection_slots):
    try:
        handle_connection(connection, address)
    finally:
        connection_slots.release()


if __name__ == "__main__":
    run_server()
