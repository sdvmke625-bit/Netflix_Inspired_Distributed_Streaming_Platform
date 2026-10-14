"""Shared validation for Django's development and secure deployment modes."""

import math
from collections import Counter

from django.core.exceptions import ImproperlyConfigured


DEPLOYMENT_ENVIRONMENTS = {"development", "demo", "production"}
INSECURE_SECRET_PREFIX = "django-insecure-"
PLACEHOLDER_DATABASE_PASSWORDS = {"", "postgres", "password", "changeme"}


def parse_bool_setting(value, *, name, default):
    if value is None or value == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")


def _has_sufficient_secret_strength(value, *, minimum_length, minimum_entropy):
    if len(value) < minimum_length or len(set(value)) < 12:
        return False
    counts = Counter(value)
    entropy = -sum(
        (count / len(value)) * math.log2(count / len(value))
        for count in counts.values()
    )
    return entropy >= minimum_entropy


def validate_runtime_security(
    *,
    service,
    environment,
    debug,
    secret_key,
    jwt_signing_key,
    allowed_hosts,
    database_user,
    database_password,
):
    if environment not in DEPLOYMENT_ENVIRONMENTS:
        raise ImproperlyConfigured(
            "DJANGO_ENV must be development, demo, or production."
        )

    if environment == "development":
        return

    problems = []
    if debug:
        problems.append("DJANGO_DEBUG must be disabled")
    if secret_key.startswith(INSECURE_SECRET_PREFIX) or not _has_sufficient_secret_strength(
        secret_key, minimum_length=50, minimum_entropy=3.5
    ):
        problems.append("DJANGO_SECRET_KEY must be explicitly configured")
    if jwt_signing_key.startswith(INSECURE_SECRET_PREFIX) or not _has_sufficient_secret_strength(
        jwt_signing_key, minimum_length=50, minimum_entropy=3.5
    ):
        problems.append("JWT_SIGNING_KEY must be explicitly configured")
    if not allowed_hosts or "*" in allowed_hosts:
        problems.append("DJANGO_ALLOWED_HOSTS must list explicit hosts")
    if not database_user.strip():
        problems.append("database user must be explicitly configured")
    if (
        database_password.strip().lower() in PLACEHOLDER_DATABASE_PASSWORDS
        or not _has_sufficient_secret_strength(
            database_password, minimum_length=16, minimum_entropy=3.5
        )
    ):
        problems.append("database password must be explicitly configured")

    if problems:
        raise ImproperlyConfigured(
            f"Insecure {environment} configuration for {service}: "
            + "; ".join(problems)
            + "."
        )
