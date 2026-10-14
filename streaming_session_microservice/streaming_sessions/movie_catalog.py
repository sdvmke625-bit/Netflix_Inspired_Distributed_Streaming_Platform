import json
import logging
import os
import random
import socket
import threading
import time

logger = logging.getLogger(__name__)

MOVIE_CATALOG_HOST = os.environ.get("MOVIE_CATALOG_TCP_HOST", "127.0.0.1")
MOVIE_CATALOG_TCP_PORT = int(os.environ.get("MOVIE_CATALOG_TCP_PORT", "9002"))
TCP_TIMEOUT_SECONDS = float(os.environ.get("MOVIE_CATALOG_TCP_TIMEOUT_SECONDS", "2"))
TCP_MAX_RETRIES = int(os.environ.get("MOVIE_CATALOG_TCP_MAX_RETRIES", "3"))
TCP_RETRY_BACKOFF_SECONDS = float(os.environ.get("MOVIE_CATALOG_TCP_RETRY_BACKOFF_SECONDS", "0.25"))
TCP_FAILURE_THRESHOLD = int(os.environ.get("MOVIE_CATALOG_TCP_FAILURE_THRESHOLD", "5"))
TCP_RECOVERY_TIMEOUT_SECONDS = float(os.environ.get("MOVIE_CATALOG_TCP_RECOVERY_TIMEOUT_SECONDS", "30"))
TCP_HALF_OPEN_LIMIT = int(os.environ.get("MOVIE_CATALOG_TCP_HALF_OPEN_LIMIT", "1"))
MAX_RESPONSE_BYTES = 1024 * 1024


class CircuitOpenError(RuntimeError):
    """Raised when a request is rejected because the TCP circuit is open."""


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold=TCP_FAILURE_THRESHOLD,
        recovery_timeout_seconds=TCP_RECOVERY_TIMEOUT_SECONDS,
        half_open_limit=TCP_HALF_OPEN_LIMIT,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_limit = half_open_limit
        self._lock = threading.RLock()
        self._state = "CLOSED"
        self._failure_count = 0
        self._opened_at = None
        self._half_open_requests = 0
        self._generation = 0

    @property
    def state(self):
        with self._lock:
            return self._state

    def before_request(self):
        with self._lock:
            now = time.monotonic()
            if self._state == "OPEN":
                if self._opened_at is not None and (now - self._opened_at) >= self.recovery_timeout_seconds:
                    self._state = "HALF_OPEN"
                    self._half_open_requests = 0
                    self._generation += 1
                    logger.info("Movie catalog TCP circuit breaker moved to HALF_OPEN")
                else:
                    raise CircuitOpenError("Movie Catalog TCP dependency is temporarily unavailable")

            if self._state == "HALF_OPEN":
                if self._half_open_requests >= self.half_open_limit:
                    raise CircuitOpenError("Movie Catalog TCP dependency is temporarily unavailable")
                self._half_open_requests += 1
            return self._generation

    def record_success(self, generation=None):
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            self._failure_count = 0
            self._half_open_requests = 0
            self._opened_at = None
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
                self._generation += 1
                logger.info("Movie catalog TCP circuit breaker recovered to CLOSED")
            self._state = "CLOSED"

    def record_failure(self, generation=None):
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            if self._state == "HALF_OPEN":
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                self._half_open_requests = 0
                self._generation += 1
                logger.warning("Movie catalog TCP circuit breaker reopened after failed recovery probe")
                return

            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                threshold = self._failure_count
                logger.warning(
                    "Movie catalog TCP circuit breaker opened after %s consecutive failures",
                    threshold,
                )
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                self._failure_count = 0
                self._generation += 1


TCP_CIRCUIT_BREAKER = CircuitBreaker()


def _read_response_data(connection, timeout_seconds=TCP_TIMEOUT_SECONDS):
    chunks = []
    deadline = time.monotonic() + timeout_seconds
    size = 0
    while True:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Movie Catalog TCP response timed out")
            connection.settimeout(remaining)
            chunk = connection.recv(4096)
        except socket.timeout as exc:
            raise TimeoutError("Movie Catalog TCP response timed out") from exc

        if not chunk:
            if not chunks:
                raise ConnectionError("Movie Catalog TCP connection closed before sending a response")
            raise ConnectionError("Movie Catalog TCP response ended before its newline frame")

        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ValueError("Movie Catalog TCP response exceeded the size limit")
        chunks.append(chunk)
        if b"\n" in chunk:
            break

    data = b"".join(chunks)
    if b"\n" not in data:
        raise ConnectionError("Movie Catalog TCP response ended before its newline frame")
    payload = data.split(b"\n", 1)[0].strip()
    if not payload:
        raise ConnectionError("Movie Catalog TCP server returned an empty response")

    try:
        response = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Movie Catalog TCP response was not valid JSON") from exc
    if not isinstance(response, dict):
        raise ValueError("Movie Catalog TCP response must be a JSON object")
    return response


def _do_get_movie_request(movie_id):
    request = {"operation": "get_movie", "movie_id": movie_id}
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(TCP_TIMEOUT_SECONDS)
    try:
        client_socket.connect((MOVIE_CATALOG_HOST, MOVIE_CATALOG_TCP_PORT))
        client_socket.sendall((json.dumps(request) + "\n").encode("utf-8"))
        response = _read_response_data(client_socket)
    finally:
        client_socket.close()

    if response.get("status") == "not_found":
        return False
    if response.get("status") != "success":
        raise ConnectionError("Movie Catalog TCP server returned an error response")
    return response.get("movie")


def get_movie(movie_id):
    try:
        breaker_generation = TCP_CIRCUIT_BREAKER.before_request()
    except CircuitOpenError:
        logger.warning("Movie request rejected because Movie Catalog circuit is open for movie_id=%s", movie_id)
        return None

    for attempt in range(TCP_MAX_RETRIES + 1):
        try:
            logger.info("Initiating TCP request for movie_id=%s (attempt %s/%s)", movie_id, attempt + 1, TCP_MAX_RETRIES + 1)
            payload = _do_get_movie_request(movie_id)
            if payload is False:
                # Movie not found - permanent application-level result, no retry
                TCP_CIRCUIT_BREAKER.record_success(breaker_generation)
                return False
            if isinstance(payload, dict) and "movie" in payload:
                movie = payload["movie"]
            else:
                movie = payload
            TCP_CIRCUIT_BREAKER.record_success(breaker_generation)
            return movie
        except (
            ConnectionError,
            OSError,
            TimeoutError,
            ValueError,
        ) as exc:
            if attempt >= TCP_MAX_RETRIES:
                TCP_CIRCUIT_BREAKER.record_failure(breaker_generation)
                logger.error(
                    "Movie Catalog TCP request failed for movie_id=%s after %s attempts: %s",
                    movie_id,
                    attempt + 1,
                    exc,
                )
                return None

            backoff = min(TCP_RETRY_BACKOFF_SECONDS * (2 ** attempt), 2.0)
            jitter = random.uniform(0, backoff * 0.25)
            sleep_time = min(backoff + jitter, 2.0)
            logger.warning(
                "Retrying Movie Catalog request for movie_id=%s (attempt %s/%s) in %.2fs after error: %s",
                movie_id,
                attempt + 1,
                TCP_MAX_RETRIES + 1,
                sleep_time,
                exc,
            )
            time.sleep(sleep_time)

    return None
