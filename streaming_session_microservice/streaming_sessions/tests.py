import time
import socket
import threading
from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from config.asgi import application
from streaming_sessions.movie_catalog import (
    CircuitBreaker,
    CircuitOpenError,
    _do_get_movie_request,
    _read_response_data,
    get_movie,
)
from streaming_sessions.models import Session


class CircuitBreakerTests(SimpleTestCase):
    def test_circuit_breaker_recovery(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.05, half_open_limit=1)
        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.state, "OPEN")

        with self.assertRaises(CircuitOpenError):
            breaker.before_request()

        time.sleep(0.06)
        breaker.before_request()
        breaker.record_success()
        self.assertEqual(breaker.state, "CLOSED")

    def test_stale_in_flight_success_does_not_close_open_circuit(self):
        breaker = CircuitBreaker(failure_threshold=1)
        request_generation = breaker.before_request()

        # A concurrent request can exhaust the threshold while this request is
        # still in flight. Its late success must not close the newer OPEN state.
        breaker.record_failure()
        breaker.record_success(request_generation)

        self.assertEqual(breaker.state, "OPEN")

    def test_circuit_breaker_half_open_failure_reopens(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.05, half_open_limit=1)
        breaker.record_failure()
        self.assertEqual(breaker.state, "OPEN")

        time.sleep(0.06)
        breaker.before_request()
        self.assertEqual(breaker.state, "HALF_OPEN")

        breaker.record_failure()
        self.assertEqual(breaker.state, "OPEN")

    def test_circuit_breaker_half_open_probe_limit_enforced(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.05, half_open_limit=1)
        breaker.record_failure()
        time.sleep(0.06)
        breaker.before_request()
        self.assertEqual(breaker.state, "HALF_OPEN")

        # Second probe exceeds limit before success or failure recorded
        with self.assertRaises(CircuitOpenError):
            breaker.before_request()

    @patch("streaming_sessions.movie_catalog.TCP_CIRCUIT_BREAKER", CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.05, half_open_limit=1))
    @patch("streaming_sessions.movie_catalog.TCP_MAX_RETRIES", 2)
    @patch("streaming_sessions.movie_catalog.TCP_RETRY_BACKOFF_SECONDS", 0)
    @patch("streaming_sessions.movie_catalog._do_get_movie_request", side_effect=[ConnectionRefusedError("down"), {"status": "success", "movie": {"id": 1, "duration": 10}}])
    def test_get_movie_retries_transient_failures(self, mock_request):
        movie = get_movie(1)
        self.assertEqual(movie["id"], 1)
        self.assertEqual(mock_request.call_count, 2)

    def test_get_movie_records_one_failure_after_bounded_retries(self):
        breaker = CircuitBreaker(failure_threshold=1)
        with (
            patch("streaming_sessions.movie_catalog.TCP_CIRCUIT_BREAKER", breaker),
            patch("streaming_sessions.movie_catalog.TCP_MAX_RETRIES", 2),
            patch("streaming_sessions.movie_catalog.TCP_RETRY_BACKOFF_SECONDS", 0),
            patch(
                "streaming_sessions.movie_catalog._do_get_movie_request",
                side_effect=ConnectionRefusedError("down"),
            ) as mock_request,
        ):
            self.assertIsNone(get_movie(1))

        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(breaker.state, "OPEN")

    def test_retry_backoff_is_capped_after_jitter(self):
        breaker = CircuitBreaker(failure_threshold=5)
        with (
            patch("streaming_sessions.movie_catalog.TCP_CIRCUIT_BREAKER", breaker),
            patch("streaming_sessions.movie_catalog.TCP_MAX_RETRIES", 2),
            patch("streaming_sessions.movie_catalog.TCP_RETRY_BACKOFF_SECONDS", 8.0),
            patch("streaming_sessions.movie_catalog.random.uniform", return_value=50.0),
            patch("streaming_sessions.movie_catalog.time.sleep") as sleep,
            patch(
                "streaming_sessions.movie_catalog._do_get_movie_request",
                side_effect=[ConnectionRefusedError("down"), ConnectionRefusedError("down"), {"id": 7}],
            ),
        ):
            self.assertEqual(get_movie(7), {"id": 7})
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.0, 2.0])

    def test_get_movie_fails_fast_when_circuit_open(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=100.0)
        breaker.record_failure()
        self.assertEqual(breaker.state, "OPEN")

        with (
            patch("streaming_sessions.movie_catalog.TCP_CIRCUIT_BREAKER", breaker),
            patch("streaming_sessions.movie_catalog._do_get_movie_request") as mock_request,
        ):
            result = get_movie(1)
            self.assertIsNone(result)
            mock_request.assert_not_called()

    def test_get_movie_non_retryable_not_found(self):
        breaker = CircuitBreaker(failure_threshold=3)
        with (
            patch("streaming_sessions.movie_catalog.TCP_CIRCUIT_BREAKER", breaker),
            patch("streaming_sessions.movie_catalog.TCP_MAX_RETRIES", 2),
            patch("streaming_sessions.movie_catalog._do_get_movie_request", return_value=False) as mock_request,
        ):
            result = get_movie(99999)
            self.assertIs(result, False)
            self.assertEqual(mock_request.call_count, 1)
            self.assertEqual(breaker.state, "CLOSED")


class TcpResponseTests(SimpleTestCase):
    def test_socket_timeout_is_set_before_connect(self):
        class FakeSocket:
            def __init__(self):
                self.timeout = None
                self.connected = False

            def settimeout(self, timeout):
                self.timeout = timeout

            def connect(self, address):
                self.connected = self.timeout is not None

            def sendall(self, data):
                self.request = data

            def close(self):
                pass

        fake = FakeSocket()
        with (
            patch("streaming_sessions.movie_catalog.socket.socket", return_value=fake),
            patch("streaming_sessions.movie_catalog._read_response_data", return_value={"status": "success", "movie": {"id": 7}}),
        ):
            self.assertEqual(_do_get_movie_request(7), {"id": 7})
        self.assertTrue(fake.connected)
        self.assertIn(b"\n", fake.request)

    def test_reads_response_fragments_until_newline(self):
        class FragmentedConnection:
            def __init__(self):
                self.chunks = iter([b'{"status":', b'"success"}\n'])

            def settimeout(self, timeout):
                pass

            def recv(self, size):
                return next(self.chunks)

        self.assertEqual(
            _read_response_data(FragmentedConnection()),
            {"status": "success"},
        )

    def test_response_timeout_is_reported(self):
        class TimedOutConnection:
            def settimeout(self, timeout):
                pass

            def recv(self, size):
                raise socket.timeout()

        with self.assertRaisesRegex(TimeoutError, "response timed out"):
            _read_response_data(TimedOutConnection(), timeout_seconds=0.1)

    def test_rejects_empty_response(self):
        class EmptyConnection:
            def settimeout(self, timeout):
                pass

            def recv(self, size):
                return b''

        with self.assertRaisesRegex(ConnectionError, "closed before sending"):
            _read_response_data(EmptyConnection(), timeout_seconds=0.1)

    def test_rejects_malformed_json_response(self):
        class MalformedConnection:
            def settimeout(self, timeout):
                pass

            def recv(self, size):
                return b'{"incomplete":\n'

        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            _read_response_data(MalformedConnection(), timeout_seconds=0.1)

    def test_rejects_response_without_newline_frame(self):
        class UnframedConnection:
            def __init__(self):
                self.sent = False

            def settimeout(self, timeout):
                pass

            def recv(self, size):
                if self.sent:
                    return b""
                self.sent = True
                return b'{"status":"success"}'

        with self.assertRaisesRegex(ConnectionError, "newline frame"):
            _read_response_data(UnframedConnection(), timeout_seconds=0.1)

    def test_live_tcp_server_recovery_after_circuit_opens(self):
        # First request observes a real refused connection. Once the recovery
        # window elapses, a real local TCP listener answers the half-open probe.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        host, port = probe.getsockname()
        probe.close()
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.03)

        with (
            patch("streaming_sessions.movie_catalog.MOVIE_CATALOG_HOST", host),
            patch("streaming_sessions.movie_catalog.MOVIE_CATALOG_TCP_PORT", port),
            patch("streaming_sessions.movie_catalog.TCP_CIRCUIT_BREAKER", breaker),
            patch("streaming_sessions.movie_catalog.TCP_MAX_RETRIES", 0),
        ):
            self.assertIsNone(get_movie(42))
            self.assertEqual(breaker.state, "OPEN")
            time.sleep(0.04)

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, port))
            listener.listen(1)

            def serve_one_request():
                peer, _ = listener.accept()
                with peer:
                    request = b""
                    while b"\n" not in request:
                        request += peer.recv(1024)
                    peer.sendall(b'{"status":"success","movie":{"id":42}}\n')
                listener.close()

            worker = threading.Thread(target=serve_one_request, daemon=True)
            worker.start()
            self.assertEqual(get_movie(42), {"id": 42})
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(breaker.state, "CLOSED")


class LoginTokenClaimsTests(TestCase):
    def test_registration_uses_configured_password_validators(self):
        client = APIClient()
        weak = client.post(
            "/api/register/",
            {"username": "weak_password_user", "password": "password"},
            format="json",
        )
        self.assertEqual(weak.status_code, 400)

        strong = client.post(
            "/api/register/",
            {"username": "strong_password_user", "password": "F!rmW!nter-3Pine@Blue"},
            format="json",
        )
        self.assertEqual(strong.status_code, 201)

    def test_login_token_marks_catalog_writer_from_staff_role(self):
        writer = User.objects.create_user(
            username="catalog_writer",
            password="test-pass-123",
            is_staff=True,
        )
        response = APIClient().post(
            "/api/login/",
            {"username": writer.username, "password": "test-pass-123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        token = AccessToken(response.data["access"])
        self.assertTrue(token["is_staff"])

    def test_login_token_does_not_grant_catalog_write_to_regular_user(self):
        user = User.objects.create_user(
            username="catalog_viewer",
            password="test-pass-123",
        )
        response = APIClient().post(
            "/api/login/",
            {"username": user.username, "password": "test-pass-123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        token = AccessToken(response.data["access"])
        self.assertFalse(token["is_staff"])



class SessionWebsocketTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="devesh",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="other",
            password="testpass123",
        )
        self.token = str(RefreshToken.for_user(self.user).access_token)
        self.other_token = str(RefreshToken.for_user(self.other_user).access_token)

    async def _connect(self):
        communicator = WebsocketCommunicator(application, "/ws/sessions/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def _authenticate(self, communicator, token):
        await communicator.send_json_to({
            "operation": "authenticate",
            "token": token,
        })
        return await communicator.receive_json_from()

    async def test_authenticate_valid_token(self):
        communicator = await self._connect()
        response = await self._authenticate(communicator, self.token)
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["operation"], "authenticate")
        self.assertEqual(response["data"]["user_id"], self.user.id)
        self.assertEqual(response["data"]["username"], "devesh")
        await communicator.disconnect()

    async def test_authenticate_missing_token(self):
        communicator = await self._connect()
        await communicator.send_json_to({"operation": "authenticate"})
        response = await communicator.receive_json_from()
        self.assertEqual(response, {
            "status": "error",
            "operation": "authenticate",
            "message": "Access token is required",
        })
        await communicator.disconnect()

    async def test_authenticate_invalid_token(self):
        communicator = await self._connect()
        response = await self._authenticate(communicator, "not-a-valid-token")
        self.assertEqual(response, {
            "status": "error",
            "operation": "authenticate",
            "message": "Invalid or expired access token",
        })
        await communicator.disconnect()

    async def test_authenticate_expired_token(self):
        expired = AccessToken.for_user(self.user)
        expired.set_exp(lifetime=timedelta(seconds=-1))
        communicator = await self._connect()
        response = await self._authenticate(communicator, str(expired))
        self.assertEqual(response, {
            "status": "error",
            "operation": "authenticate",
            "message": "Invalid or expired access token",
        })
        await communicator.disconnect()

    async def test_protected_operations_require_authentication(self):
        communicator = await self._connect()
        for operation, payload in [
            ("list_sessions", {"operation": "list_sessions"}),
            ("create_session", {"operation": "create_session", "movie_id": 1}),
            ("update_session", {
                "operation": "update_session",
                "session_id": 1,
                "playback_position": 1,
            }),
        ]:
            await communicator.send_json_to(payload)
            response = await communicator.receive_json_from()
            self.assertEqual(
                response,
                {"status": "error", "message": "Authentication required"},
                msg=operation,
            )
        await communicator.disconnect()

    async def test_list_sessions_returns_only_authenticated_user_sessions(self):
        own_session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=10,
            movie_duration=120,
            playback_position=15,
            status="paused",
        )
        await sync_to_async(Session.objects.create)(
            user=self.other_user,
            movie_id=11,
            movie_duration=90,
            playback_position=5,
            status="playing",
        )

        communicator = await self._connect()
        auth = await self._authenticate(communicator, self.token)
        self.assertEqual(auth["status"], "success")

        await communicator.send_json_to({"operation": "list_sessions"})
        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["operation"], "list_sessions")
        self.assertEqual(len(response["data"]), 1)
        self.assertEqual(response["data"][0]["id"], own_session.id)
        self.assertEqual(response["data"][0]["user"], self.user.id)
        self.assertNotIn("other", [item["user"] for item in response["data"]])
        await communicator.disconnect()

    @patch("streaming_sessions.consumers.get_movie")
    async def test_create_session_valid_movie(self, mock_get_movie):
        mock_get_movie.return_value = {"id": 40, "duration": 120}

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "create_session",
            "movie_id": 40,
            "movie_duration": 120,
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["operation"], "create_session")
        self.assertEqual(response["data"]["movie_id"], 40)
        self.assertEqual(response["data"]["movie_duration"], 120)
        self.assertEqual(response["data"]["user"], self.user.id)
        self.assertEqual(response["data"]["playback_position"], 0)
        self.assertEqual(response["data"]["status"], "playing")
        mock_get_movie.assert_called_once_with(40)
        await communicator.disconnect()

    @patch("streaming_sessions.consumers.get_movie")
    async def test_create_session_invalid_movie(self, mock_get_movie):
        mock_get_movie.return_value = False

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "create_session",
            "movie_id": 999,
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response, {
            "status": "error",
            "operation": "create_session",
            "message": "Movie not found",
        })
        self.assertFalse(
            await sync_to_async(Session.objects.filter(user=self.user).exists)()
        )
        await communicator.disconnect()

    @patch("streaming_sessions.consumers.get_movie")
    async def test_create_session_catalog_unavailable(self, mock_get_movie):
        mock_get_movie.return_value = None

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "create_session",
            "movie_id": 40,
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response, {
            "status": "error",
            "operation": "create_session",
            "message": "Movie Catalog Service is unavailable.",
        })
        self.assertFalse(
            await sync_to_async(Session.objects.filter(user=self.user).exists)()
        )
        await communicator.disconnect()

    async def test_update_session_valid(self):
        session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=15,
            movie_duration=120,
            playback_position=10,
            status="playing",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "playback_position": 72,
            "status": "paused",
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["operation"], "update_session")
        self.assertEqual(response["data"]["id"], session.id)
        self.assertEqual(response["data"]["playback_position"], 72)
        self.assertEqual(response["data"]["status"], "paused")
        self.assertEqual(response["data"]["version"], 1)
        await communicator.disconnect()

    async def test_update_session_version_conflict(self):
        session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=15,
            movie_duration=120,
            playback_position=10,
            status="playing",
            version=0,
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "version": 0,
            "playback_position": 40,
            "status": "paused",
        })
        first_response = await communicator.receive_json_from()
        self.assertEqual(first_response["status"], "success")
        self.assertEqual(first_response["data"]["version"], 1)

        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "version": 0,
            "playback_position": 80,
            "status": "playing",
        })
        stale_response = await communicator.receive_json_from()
        self.assertEqual(stale_response["status"], "error")
        self.assertEqual(stale_response["operation"], "update_session")
        self.assertEqual(stale_response["message"], "Session version conflict")
        await sync_to_async(session.refresh_from_db)()
        self.assertEqual(session.playback_position, 40)
        self.assertEqual(session.version, 1)
        await communicator.disconnect()

    async def test_update_session_invalid_playback_position(self):
        session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=15,
            movie_duration=120,
            playback_position=10,
            status="playing",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "playback_position": 200,
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["operation"], "update_session")
        self.assertIn("playback_position", response["message"])
        await sync_to_async(session.refresh_from_db)()
        self.assertEqual(session.playback_position, 10)
        await communicator.disconnect()

    async def test_update_session_invalid_status_transition(self):
        session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=15,
            movie_duration=120,
            playback_position=10,
            status="ended",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "status": "playing",
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["operation"], "update_session")
        self.assertIn("Cannot change session status", response["message"])
        await sync_to_async(session.refresh_from_db)()
        self.assertEqual(session.status, "ended")
        await communicator.disconnect()

    async def test_update_completed_session_playback_position_is_rejected(self):
        session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=15,
            movie_duration=120,
            playback_position=120,
            status="ended",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "playback_position": 50,
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["operation"], "update_session")
        self.assertIn("Completed sessions cannot be updated", response["message"])
        await sync_to_async(session.refresh_from_db)()
        self.assertEqual(session.playback_position, 120)
        self.assertEqual(session.status, "ended")
        await communicator.disconnect()

    @patch("streaming_sessions.consumers.get_movie")
    async def test_watch_again_creates_new_incomplete_session(self, mock_get_movie):
        mock_get_movie.return_value = {"id": 40, "duration": 120}
        completed_session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=40,
            movie_duration=120,
            playback_position=120,
            status="ended",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "create_session",
            "movie_id": 40,
        })
        response = await communicator.receive_json_from()

        self.assertEqual(response["status"], "success")
        self.assertNotEqual(response["data"]["id"], completed_session.id)
        self.assertEqual(response["data"]["playback_position"], 0)
        self.assertEqual(response["data"]["status"], "playing")

        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": response["data"]["id"],
            "playback_position": 120,
        })
        completed_again = await communicator.receive_json_from()
        self.assertEqual(completed_again["status"], "success")
        self.assertEqual(completed_again["data"]["status"], "ended")

        await sync_to_async(completed_session.refresh_from_db)()
        self.assertEqual(completed_session.playback_position, 120)
        self.assertEqual(completed_session.status, "ended")
        self.assertEqual(
            await sync_to_async(Session.objects.filter(
                user=self.user,
                movie_id=40,
                status="ended",
            ).count)(),
            2,
        )
        await communicator.disconnect()

    async def test_update_session_ended_at_movie_duration(self):
        session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=15,
            movie_duration=120,
            playback_position=10,
            status="playing",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "playback_position": 120,
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["data"]["status"], "ended")
        self.assertEqual(response["data"]["playback_position"], 120)
        await communicator.disconnect()

    async def test_duplicate_completion_update_is_idempotent(self):
        session = await sync_to_async(Session.objects.create)(
            user=self.user,
            movie_id=15,
            movie_duration=120,
            playback_position=115,
            status="playing",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)

        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "playback_position": 120,
        })
        first_response = await communicator.receive_json_from()
        self.assertEqual(first_response["status"], "success")
        self.assertEqual(first_response["data"]["status"], "ended")

        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session.id,
            "status": "ended",
            "playback_position": 120,
        })
        duplicate_response = await communicator.receive_json_from()
        self.assertEqual(duplicate_response["status"], "success")
        self.assertEqual(duplicate_response["data"]["status"], "ended")
        self.assertEqual(duplicate_response["data"]["playback_position"], 120)
        self.assertEqual(
            duplicate_response["data"]["updated_at"],
            first_response["data"]["updated_at"],
        )

        await sync_to_async(session.refresh_from_db)()
        self.assertEqual(session.status, "ended")
        self.assertEqual(session.playback_position, 120)
        await communicator.disconnect()

    async def test_update_session_another_users_session(self):
        other_session = await sync_to_async(Session.objects.create)(
            user=self.other_user,
            movie_id=15,
            movie_duration=120,
            playback_position=10,
            status="playing",
        )

        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": other_session.id,
            "playback_position": 50,
            "status": "paused",
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response, {
            "status": "error",
            "operation": "update_session",
            "message": "Session not found",
        })
        await sync_to_async(other_session.refresh_from_db)()
        self.assertEqual(other_session.playback_position, 10)
        await communicator.disconnect()

    async def test_update_session_nonexistent(self):
        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": 99999,
            "playback_position": 10,
        })
        response = await communicator.receive_json_from()
        self.assertEqual(response, {
            "status": "error",
            "operation": "update_session",
            "message": "Session not found",
        })
        await communicator.disconnect()

    @patch("streaming_sessions.consumers.get_movie")
    async def test_multiple_operations_on_same_connection(self, mock_get_movie):
        mock_get_movie.return_value = {"id": 40, "duration": 120}

        communicator = await self._connect()
        auth = await self._authenticate(communicator, self.token)
        self.assertEqual(auth["status"], "success")

        await communicator.send_json_to({"operation": "list_sessions"})
        listed = await communicator.receive_json_from()
        self.assertEqual(listed["status"], "success")
        self.assertEqual(listed["data"], [])

        await communicator.send_json_to({
            "operation": "create_session",
            "movie_id": 40,
        })
        created = await communicator.receive_json_from()
        self.assertEqual(created["status"], "success")
        session_id = created["data"]["id"]

        await communicator.send_json_to({
            "operation": "update_session",
            "session_id": session_id,
            "playback_position": 20,
            "status": "paused",
        })
        updated = await communicator.receive_json_from()
        self.assertEqual(updated["status"], "success")
        self.assertEqual(updated["data"]["playback_position"], 20)
        self.assertEqual(updated["data"]["status"], "paused")

        await communicator.send_json_to({"operation": "list_sessions"})
        listed_again = await communicator.receive_json_from()
        self.assertEqual(len(listed_again["data"]), 1)
        self.assertEqual(listed_again["data"][0]["id"], session_id)
        await communicator.disconnect()

    async def test_invalid_json(self):
        communicator = await self._connect()
        await communicator.send_to(text_data="this is not valid json")
        response = await communicator.receive_json_from()
        self.assertEqual(response, {
            "status": "error",
            "message": "Invalid JSON",
        })
        await communicator.disconnect()

    async def test_unknown_operation(self):
        communicator = await self._connect()
        await self._authenticate(communicator, self.token)
        await communicator.send_json_to({"operation": "some_random_op"})
        response = await communicator.receive_json_from()
        self.assertEqual(response, {
            "status": "error",
            "message": "Unknown operation",
        })
        await communicator.disconnect()
