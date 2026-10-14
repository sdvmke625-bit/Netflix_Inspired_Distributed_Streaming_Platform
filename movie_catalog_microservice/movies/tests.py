from datetime import date
import secrets
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from deployment_security import parse_bool_setting, validate_runtime_security

from .consumer import MovieConsumer
from .models import Movie
from .tcp_server import handle_request, read_request


class MovieWebSocketMessageTests(SimpleTestCase):
    def test_rejects_non_object_json_without_closing_connection(self):
        async def exercise():
            communicator = WebsocketCommunicator(MovieConsumer.as_asgi(), "/ws/movies/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            try:
                await communicator.send_to(text_data="[]")
                response = await communicator.receive_json_from()
                self.assertEqual(
                    response,
                    {"status": "error", "message": "Invalid JSON"},
                )
            finally:
                await communicator.disconnect()

        async_to_sync(exercise)()


class TcpRequestTests(TestCase):
    def test_reads_a_request_sent_in_fragments(self):
        class FragmentedConnection:
            def __init__(self):
                self.chunks = iter([
                    b'{"operation":',
                    b'"get_movie","movie_id":7}\n',
                ])

            def recv(self, size):
                return next(self.chunks)

        self.assertEqual(
            read_request(FragmentedConnection()),
            {"operation": "get_movie", "movie_id": 7},
        )

    def test_rejects_non_object_json(self):
        class SingleChunkConnection:
            def recv(self, size):
                return b'["get_movie"]\n'

        with self.assertRaisesRegex(ValueError, "JSON object"):
            read_request(SingleChunkConnection())

    def test_rejects_empty_request(self):
        class EmptyConnection:
            def recv(self, size):
                return b'\n'

        with self.assertRaisesRegex(ValueError, "empty"):
            read_request(EmptyConnection())

    def test_rejects_request_without_newline_frame(self):
        class UnframedConnection:
            def __init__(self):
                self.sent = False

            def recv(self, size):
                if self.sent:
                    return b""
                self.sent = True
                return b'{"operation":"health"}'

        with self.assertRaisesRegex(ValueError, "newline"):
            read_request(UnframedConnection())


class TcpHandlerTests(TestCase):
    def setUp(self):
        self.movie = Movie.objects.create(
            title="Inception",
            description="Dream inside a dream",
            genre="Sci-Fi",
            duration=8880,
            release_date=date(2010, 7, 16),
            video_url="/videos/inception.mp4",
        )

    def test_health_check_operation(self):
        response = handle_request({"operation": "health"})
        self.assertEqual(response.get("status"), "success")
        self.assertEqual(response.get("operation"), "health")

    def test_empty_connection_is_silent_for_tcp_health_probes(self):
        class ProbeConnection:
            def __init__(self):
                self.response = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, _timeout):
                pass

            def recv(self, _size):
                return b""

            def sendall(self, data):
                self.response = data

        connection = ProbeConnection()
        from .tcp_server import handle_connection

        handle_connection(connection, ("127.0.0.1", 12345))
        self.assertIsNone(connection.response)

    def test_get_movie_success(self):
        response = handle_request({"operation": "get_movie", "movie_id": self.movie.id})
        self.assertEqual(response.get("status"), "success")
        self.assertEqual(response["movie"]["title"], "Inception")
        self.assertEqual(response["movie"]["duration"], 8880)

    def test_get_movie_not_found(self):
        response = handle_request({"operation": "get_movie", "movie_id": 99999})
        self.assertEqual(response.get("status"), "not_found")

    def test_get_movie_missing_id(self):
        response = handle_request({"operation": "get_movie"})
        self.assertEqual(response.get("status"), "error")
        self.assertIn("movie_id is required", response.get("message", ""))

    def test_unknown_operation(self):
        response = handle_request({"operation": "unknown_op"})
        self.assertEqual(response.get("status"), "error")
        self.assertIn("Invalid request", response.get("message", ""))


class MovieWriteAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.movie = Movie.objects.create(
            title="Public Movie",
            description="A public catalog entry",
            genre="Drama",
            duration=120,
            release_date=date(2024, 1, 1),
            video_url="/videos/public.mp4",
        )
        self.payload = {
            "title": "Writer Movie",
            "description": "Created by a catalog writer",
            "genre": "Drama",
            "duration": 180,
            "release_date": "2024-02-01",
            "video_url": "/videos/writer.mp4",
        }

    @staticmethod
    def authorization_for(*, is_staff):
        user = User.objects.create_user(username=f"writer_{is_staff}", password="test-pass-123")
        token = AccessToken.for_user(user)
        token["is_staff"] = is_staff
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_public_list_and_detail_remain_readable(self):
        self.assertEqual(self.client.get("/api/movies/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/movies/{self.movie.pk}/").status_code, 200)

    def test_anonymous_writes_are_rejected(self):
        self.assertEqual(self.client.post("/api/movies/", self.payload, format="json").status_code, 401)
        url = f"/api/movies/{self.movie.pk}/"
        self.assertEqual(self.client.put(url, self.payload, format="json").status_code, 401)
        self.assertEqual(self.client.delete(url).status_code, 401)
        self.assertEqual(Movie.objects.count(), 1)

    def test_authenticated_non_staff_writes_are_rejected(self):
        auth = self.authorization_for(is_staff=False)
        self.assertEqual(self.client.post("/api/movies/", self.payload, format="json", **auth).status_code, 403)
        url = f"/api/movies/{self.movie.pk}/"
        self.assertEqual(self.client.put(url, self.payload, format="json", **auth).status_code, 403)
        self.assertEqual(self.client.delete(url, **auth).status_code, 403)
        self.assertEqual(Movie.objects.count(), 1)

    def test_staff_writer_can_create_update_and_delete(self):
        auth = self.authorization_for(is_staff=True)
        created = self.client.post("/api/movies/", self.payload, format="json", **auth)
        self.assertEqual(created.status_code, 201)
        movie_id = created.data["id"]

        updated_payload = {**self.payload, "title": "Writer Movie Updated"}
        updated = self.client.put(
            f"/api/movies/{movie_id}/", updated_payload, format="json", **auth
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["title"], "Writer Movie Updated")

        deleted = self.client.delete(f"/api/movies/{movie_id}/", **auth)
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Movie.objects.filter(pk=movie_id).exists())


class RuntimeSecurityValidationTests(TestCase):
    secure_settings = {
        "service": "test",
        "environment": "demo",
        "debug": False,
        "secret_key": secrets.token_urlsafe(48),
        "jwt_signing_key": secrets.token_urlsafe(48),
        "allowed_hosts": ["localhost", "127.0.0.1"],
        "database_user": "netflix_app",
        "database_password": secrets.token_urlsafe(32),
    }

    def test_secure_demo_configuration_is_accepted(self):
        validate_runtime_security(**self.secure_settings)

    def test_demo_configuration_rejects_development_defaults(self):
        unsafe = {
            **self.secure_settings,
            "debug": True,
            "secret_key": "django-insecure-placeholder",
            "jwt_signing_key": "django-insecure-placeholder",
            "allowed_hosts": ["*"],
            "database_user": "postgres",
            "database_password": "postgres",
        }
        with self.assertRaisesMessage(ImproperlyConfigured, "Insecure demo configuration"):
            validate_runtime_security(**unsafe)

    def test_demo_configuration_rejects_long_but_low_entropy_secrets(self):
        unsafe = {
            **self.secure_settings,
            "secret_key": "a" * 64,
            "jwt_signing_key": "b" * 64,
            "database_password": "c" * 32,
        }
        with self.assertRaisesMessage(ImproperlyConfigured, "Insecure demo configuration"):
            validate_runtime_security(**unsafe)

    def test_boolean_parser_rejects_ambiguous_values(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_DEBUG must be a boolean"):
            parse_bool_setting("sometimes", name="DJANGO_DEBUG", default=False)
